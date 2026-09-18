"""Versioned, evidence-based IRT assessment. Pure input/validation/aggregation code."""
import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ASSESSMENT_SCHEMA_VERSION = 'intent-2'

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Judgment(StrictModel):
    instance_id: int
    grade: Literal['full', 'incidental', 'missing']
    question_message_ids: list[int]
    answer_message_ids: list[int]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


class Act(StrictModel):
    message_id: int
    kind: Literal['question', 'confirmation', 'explanation', 'other']
    quote: str = Field(min_length=1)


class Assessment(StrictModel):
    judgments: list[Judgment]
    acts: list[Act]


TOOL = dict(type='function', name='submit_intent_assessment',
            description='項目ごとの聴取の評価と保健師発言の意味単位分類を提出する',
            parameters=Assessment.model_json_schema())


def parse_day(value):
    match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', str(value or ''))
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


def make_input(session, items, logs, knowledge_context=''):
    """Freeze only relevant, non-secret input; never substitute today's date."""
    day = parse_day(session.get('interview_date'))
    weekdays = '月火水木金土日'
    calendar = [] if day is None else [
        dict(date=(day + timedelta(days=n)).isoformat(),
             weekday=weekdays[(day + timedelta(days=n)).weekday()]) for n in range(-21, 3)]
    dialogue = []
    for log in logs:
        if log['sender'] not in ('User', 'Assistant') or not log.get('message'):
            continue
        role = log.get('ai_role') or log.get('user_role')
        if log['sender'] == 'Assistant' and not log.get('ai_role'):
            role = '患者' if log.get('user_role') == '保健師' else '保健師'
        if role not in ('患者', '保健師'):
            continue
        dialogue.append(dict(id=log['id'], role=role, text=log['message'],
                             initial=bool(log.get('is_initial_message'))))
    selected = [dict(id=i['id'], item_type_code=i['item_type_code'],
                     instance_number=i['instance_number'], description=i.get('description') or '',
                     catalog_version=i.get('catalog_version'),
                     risk_score=i.get('pairwise_risk_score'))
                for i in items if i.get('is_detectable', True) and not i.get('is_excluded_from_analysis', False)]
    if not selected or not dialogue or len({x['id'] for x in selected}) != len(selected):
        raise ValueError('Items/dialogue empty or item IDs duplicated')
    if len({x['id'] for x in dialogue}) != len(dialogue):
        raise ValueError('Duplicate message IDs')
    return dict(schema_version=ASSESSMENT_SCHEMA_VERSION, session_id=session['session_id'], patient_id=session['patient_id'],
                interview_date=session.get('interview_date'), calendar=calendar,
                knowledge_context=knowledge_context,
                items=selected, dialogue=dialogue)


def input_hash(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_assessment(raw, payload):
    result = Assessment.model_validate(raw)
    ids = [j.instance_id for j in result.judgments]
    if len(ids) != len(set(ids)) or set(ids) != {i['id'] for i in payload['items']}:
        raise ValueError('Missing, duplicated or foreign item IDs')
    dialogue = {m['id']: m for m in payload['dialogue']}
    order = {m['id']: n for n, m in enumerate(payload['dialogue'])}
    nurses = {m['id'] for m in payload['dialogue'] if m['role'] == '保健師' and not m['initial']}
    positions, kinds = {}, {}
    for act in result.acts:
        if act.message_id not in nurses:
            raise ValueError('Act refers to non-nurse/initial/foreign message')
        text = dialogue[act.message_id]['text']
        pos = positions.get(act.message_id, 0)
        start = text.find(act.quote, pos)
        if start < 0 or text[pos:start].strip():
            raise ValueError('Act quote is changed, reordered, overlapping or incomplete')
        positions[act.message_id] = start + len(act.quote)
        kinds.setdefault(act.message_id, set()).add(act.kind)
    if set(positions) != nurses:
        raise ValueError('Missing nurse message classification')
    for mid, pos in positions.items():
        if dialogue[mid]['text'][pos:].strip():
            raise ValueError('Act quotes do not cover message')
    for j in result.judgments:
        # Drop unrelated evidence IDs without changing an otherwise supported grade.
        # In particular, a missing/incidental judgment does not require a question.
        questions = [mid for mid in j.question_message_ids
                     if mid in nurses and kinds[mid].intersection({'question', 'confirmation'})]
        answers = [mid for mid in j.answer_message_ids
                   if mid in dialogue and dialogue[mid]['role'] == '患者' and not dialogue[mid]['initial']]
        note = None
        if j.grade in ('full', 'incidental') and not answers:
            j.grade = 'missing'
            note = '必要な情報を示す患者回答の根拠が確認できないため×。'
        elif j.grade == 'full' and not any(order[q] < order[a] for q in questions for a in answers):
            j.grade = 'incidental'
            note = '患者回答に情報はあるが、その項目を質問・確認して聞き出した根拠が確認できないため△。'
        if note:
            j.reason = note + '元の判定理由：' + j.reason
            j.confidence = 0.0
        j.question_message_ids = questions
        j.answer_message_ids = answers
    return result.model_dump()


def summarize(raw, payload):
    raw = validate_assessment(raw, payload)
    by_id = {j['instance_id']: j for j in raw['judgments']}
    counts = Counter(j['grade'] for j in raw['judgments'])
    acts = Counter(a['kind'] for a in raw['acts'])
    items = [dict(instance_id=i['id'], item_type_code=i['item_type_code'], description=i['description'],
                  risk_score=i['risk_score'], collected=by_id[i['id']]['grade'] == 'full', **{
                      k: v for k, v in by_id[i['id']].items() if k != 'instance_id'}) for i in payload['items']]
    display = len(payload['dialogue'])
    substantive = [m for m in payload['dialogue'] if not m['initial']]
    nurses = [m for m in substantive if m['role'] == '保健師']
    denominator = len(items)
    score = counts['full'] / denominator if denominator else None
    return dict(patient_id=payload['patient_id'], assessment_version=ASSESSMENT_SCHEMA_VERSION,
                evaluator_prompt_version=payload.get('assessment', {}).get('prompt_version'),
                evaluator_model=payload.get('assessment', {}).get('model'),
                score=score, total_item_count=len(items), assessed_item_count=denominator,
                collected_item_count=counts['full'], incidental_item_count=counts['incidental'],
                missing_item_count=counts['missing'],
                items=items, message_count=len(substantive), display_message_count=display,
                initial_message_count=display-len(substantive), nurse_turn_count=len(nurses),
                question_count=acts['question'], confirmation_count=acts['confirmation'],
                explanation_count=acts['explanation'], other_act_count=acts['other'],
                legacy_question_mark_count=sum(m['text'].count('?')+m['text'].count('？') for m in nurses),
                correct_per_10_questions=None, acts=raw['acts'], interview_date=payload['interview_date'])
