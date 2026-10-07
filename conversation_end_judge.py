"""会話終了判定（TypeSafe Jev）。保健師AIの終了ツールと終了検出用LLMを置き換える。

判定は患者側の発言の直後に行い、直近の発言だけを state として渡す。
Jev は一つの質問に複数の判断を含めると精度が落ちるため、
「保健師が締めくくったか」と「患者がそれに応じたか」を別の Noul で聞き、コードで結合する。
"""
import logging
import os
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

API_URL = 'https://api.typesafe.ai/v1/systemone'
RECENT_MESSAGES = 6
SPEAKERS = {'保健師': 'nurse', '患者': 'patient'}

QUESTIONS = {
    'nurse_closed': {
        'type': 'noul',
        'instructions': ('Does the last message by the nurse in `conversation` end the interview by thanking '
                         'the patient or saying farewell, without asking the patient anything?'),
        'criteria': {
            'true': ("The nurse's last message thanks the patient for cooperating or says farewell "
                     '(for example, wishing them a quick recovery), and contains no question at all.'),
            'false': ("The nurse's last message contains any question, including a final check such as "
                      'whether the patient has anything else to add or forgot to mention, '
                      'or the interview continues.'),
        },
    },
    'patient_acknowledged': {
        'type': 'noul',
        'instructions': ("Does the patient's final message in `conversation` leave nothing more to discuss "
                         "after the nurse's last message?"),
        'criteria': {
            'true': ("The patient accepts the nurse's closing, for example with thanks or agreement, "
                     'and raises no new information or question.'),
            'false': ('The patient answers with new information about symptoms, places, people, or activities, '
                      'or asks something, so the interview should continue.'),
        },
    },
}


class ConversationEndJudge:
    def __init__(self, model: str, threshold: float, api_key: Optional[str] = None, timeout: float = 15.0):
        self.model = model
        self.threshold = threshold
        self.api_key = api_key if api_key is not None else os.getenv('TYPESAFE_API_KEY')
        self.timeout = timeout
        if not self.api_key:
            logger.warning('TYPESAFE_API_KEY is not set; conversation end judgment is disabled.')

    async def check(self, messages: List[Tuple[str, str]]) -> Optional[dict]:
        """messages: 発言順の (役割, 本文)。役割は '保健師' / '患者'。
        判定不能・失敗時は None（呼び出し側は会話を継続する）。"""
        turns = [dict(speaker=SPEAKERS[role], text=text) for role, text in messages if role in SPEAKERS and text]
        # 最後が患者の発言で、その前に保健師の発言があるときだけ判定する（コードで決まることはコードで判定）
        if not self.api_key or not turns or turns[-1]['speaker'] != 'patient' \
                or not any(t['speaker'] == 'nurse' for t in turns):
            return None
        body = dict(model=self.model, state=dict(conversation=turns[-RECENT_MESSAGES:]), questions=QUESTIONS)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(API_URL, json=body,
                                             headers={'Authorization': f'Bearer {self.api_key}'})
                response.raise_for_status()
                data = response.json()
            answers = data['answers']
            closed = float(answers['nurse_closed']['noul'])
            acknowledged = float(answers['patient_acknowledged']['noul'])
        except Exception as exc:
            logger.error('Conversation end judgment failed: %s', type(exc).__name__)
            return None
        result = dict(ended=closed >= self.threshold and acknowledged >= self.threshold,
                      nurse_closed=closed, patient_acknowledged=acknowledged,
                      model=data.get('model'), threshold=self.threshold)
        logger.info('Conversation end judgment: %s', result)
        return result


async def judge_session_end(session) -> bool:
    """WebSocketセッション（APISession）の患者側発言の直後に呼ぶ。
    「会話を続ける」を選んだ直後は、同じ締めくくりで再び終了と判定しないよう1回だけ判定を飛ばす。"""
    judge = getattr(session, 'conversation_end_judge', None)
    if judge is None:
        return False
    if session.skip_next_end_detection:
        session.skip_next_end_detection = False
        logger.info('Skipping conversation end judgment (continue request)')
        return False
    result = await judge.check([(m.role, m.text) for m in session.history.history])
    return bool(result and result['ended'])
