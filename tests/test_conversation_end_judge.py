"""会話終了判定（Jev）を、TypeSafe API を呼ばずに検証する。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import conversation_end_judge as cej
from conversation_end_judge import ConversationEndJudge, judge_session_end


def fake_client(answers=None, error=None, calls=None):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            if calls is not None:
                calls.append(dict(url=url, json=json, headers=headers))
            if error:
                raise error
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: dict(model='jev-1.13.0', answers=answers))
    return Client


def answers(closed, ack):
    return dict(nurse_closed=dict(type='noul', noul=closed), patient_acknowledged=dict(type='noul', noul=ack))


CLOSING = [('保健師', '発症日は？'), ('患者', '4月20日です。'),
           ('保健師', 'ご協力ありがとうございました。お大事に。'), ('患者', 'ありがとうございました。')]


class ConversationEndJudgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.judge = ConversationEndJudge('jev-1.13.0', 0.5, api_key='test-key')

    async def test_both_judgments_must_pass_and_pinned_model_and_recent_turns_are_sent(self):
        calls = []
        long_history = [('保健師', f'質問{i}') if i % 2 == 0 else ('患者', f'回答{i}') for i in range(20)] + CLOSING
        with patch.object(cej.httpx, 'AsyncClient', fake_client(answers(0.9, 0.8), calls=calls)):
            result = await self.judge.check(long_history)
        self.assertTrue(result['ended'])
        body = calls[0]['json']
        self.assertEqual(body['model'], 'jev-1.13.0')
        self.assertEqual(len(body['state']['conversation']), cej.RECENT_MESSAGES)
        self.assertEqual(body['state']['conversation'][-1], dict(speaker='patient', text='ありがとうございました。'))
        self.assertEqual(set(body['questions']), {'nurse_closed', 'patient_acknowledged'})
        self.assertEqual(calls[0]['headers']['Authorization'], 'Bearer test-key')
        with patch.object(cej.httpx, 'AsyncClient', fake_client(answers(0.9, 0.3))):
            self.assertFalse((await self.judge.check(CLOSING))['ended'])

    async def test_not_judged_unless_patient_spoke_last_or_key_missing(self):
        calls = []
        with patch.object(cej.httpx, 'AsyncClient', fake_client(answers(1, 1), calls=calls)):
            self.assertIsNone(await self.judge.check(CLOSING[:-1]))
            self.assertIsNone(await self.judge.check([('患者', 'こんにちは')]))
            self.assertIsNone(await ConversationEndJudge('jev-1.13.0', 0.5, api_key='').check(CLOSING))
        self.assertEqual(calls, [])

    async def test_failure_means_continue(self):
        with patch.object(cej.httpx, 'AsyncClient', fake_client(error=RuntimeError('down'))):
            self.assertIsNone(await self.judge.check(CLOSING))

    async def test_session_judgment_skips_once_after_continue_request(self):
        session = SimpleNamespace(conversation_end_judge=self.judge, skip_next_end_detection=True,
                                  history=SimpleNamespace(history=[SimpleNamespace(role=r, text=t) for r, t in CLOSING]))
        with patch.object(cej.httpx, 'AsyncClient', fake_client(answers(0.9, 0.9))):
            self.assertFalse(await judge_session_end(session))
            self.assertFalse(session.skip_next_end_detection)
            self.assertTrue(await judge_session_end(session))
        self.assertFalse(await judge_session_end(SimpleNamespace(conversation_end_judge=None)))


class BatchConversationEndTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_ends_by_judgment_without_end_tool(self):
        from irt_batch_runner import HeadlessConversation
        replies = iter(['4月20日です。', 'ご協力ありがとうございました。', 'ありがとうございました。', '予備'])
        oaw = SimpleNamespace(create_thread=AsyncMock(side_effect=['n', 'p']), add_message_to_thread=AsyncMock(),
                              delete_thread_by_id=AsyncMock(),
                              send_message=AsyncMock(side_effect=lambda *a, **kw: (next(replies), None)))
        provider = SimpleNamespace(get_patient_prompt_chunks=lambda *a, **kw: (['患者設定'], '2022年04月22日'),
                                   get_patient_details=lambda *a: dict(name='川原 一真'),
                                   get_interviewer_prompt_chunks=lambda *a, **kw: (['保健師設定'], '体調はいかがですか？'))
        judge = SimpleNamespace(check=AsyncMock(side_effect=lambda h: dict(ended=h[-1][1] == 'ありがとうございました。')))
        conv = HeadlessConversation(oaw, provider, db=None, end_judge=judge)
        with patch('irt_batch_runner.log_message', AsyncMock()):
            result = await conv.run('60', 'session-1')
        self.assertEqual(result['ended_by'], 'end_judge')
        self.assertEqual(result['turn_count'], 3)
        for call in oaw.send_message.call_args_list:
            self.assertEqual(call.kwargs['tools'], [])
        self.assertEqual(judge.check.await_count, 2)  # 患者の発言の後だけ判定する


class ObserverConversationEndTest(unittest.IsolatedAsyncioTestCase):
    async def test_observer_loop_sends_end_choices_when_judged_ended(self):
        """傍聴者モードの会話ループが、終了判定で選択肢を送って止まる（2026-10-07 の UnboundLocalError の回帰）。"""
        import logging
        from ai_conversation_manager import AIConversationManager
        from modelHistory import History, MessageInfo
        from modelUserDef import AssistantDef
        sent = []
        ws = SimpleNamespace(send_json=AsyncMock(side_effect=lambda m: sent.append(m)))
        judge = SimpleNamespace(check=AsyncMock(return_value=dict(ended=True)))
        session = SimpleNamespace(session_id='s', skip_next_end_detection=False, conversation_end_judge=judge,
                                  history=History(history=[MessageInfo(role='保健師', text='ご協力ありがとうございました。')]))
        oaw = SimpleNamespace(send_message=AsyncMock(return_value=('ありがとうございました。', None)))
        manager = AIConversationManager(session, SimpleNamespace(ws=ws, role='傍聴者'), oaw, None, None,
                                        logging.getLogger('test'))
        manager.nurse_ai = AssistantDef(user_id='n', role='保健師', assistant_id='a')
        manager.patient_ai = AssistantDef(user_id='p', role='患者', assistant_id='b')
        manager.initial_message_sent = True
        manager.message_interval = 0
        with patch('ai_conversation_manager.log_message', AsyncMock()), \
                patch('ai_conversation_manager.record_response_model'):
            manager.is_running = True
            await manager._conversation_loop()
        types = [m['msg_type'] for m in sent]
        self.assertEqual(types, ['MessageForwarded', 'ConversationEndChoices'])
        self.assertFalse(manager.is_running)


if __name__ == '__main__':
    unittest.main()
