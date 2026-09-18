"""One assessment path for interactive requests and offline/batch pilots."""
import asyncio
import json
import logging
import uuid

from intent_assessment import ASSESSMENT_SCHEMA_VERSION, TOOL, input_hash, make_input, summarize, validate_assessment
from modelUserDef import AssistantDef

MAX_OUTPUT_TOKENS = 10000


class AssessmentConfigurationError(ValueError):
    """The selected managed evaluator cannot be used by the current grading API."""


class AssessmentOutputError(ValueError):
    """The evaluator did not return an assessment that can be safely displayed."""


async def assess(oaw, payload):
    """Return original model output; validation belongs to the shared aggregation path."""
    thread = await oaw.create_thread()
    try:
        assistant = AssistantDef(user_id=str(uuid.uuid4()), role='評価者',
                                 assistant_id='intent-rubric', thread_id=thread)
        # Explicit instructions/model avoid inheriting a legacy assistant's rubric.
        _, call = await oaw.send_message(assistant, json.dumps(payload, ensure_ascii=False),
                                         instructions=payload['assessment']['instructions'],
                                         model=payload['assessment']['model'], tools=[TOOL],
                                         tool_choice='required', max_retries=0,
                                         max_output_tokens=MAX_OUTPUT_TOKENS, truncation='disabled')
        if call is None or call.name != TOOL['name']:
            raise AssessmentOutputError('評価AIから採点結果を取得できませんでした。結果は保存されていません。')
        try:
            return json.loads(call.arguments)
        except json.JSONDecodeError as exc:
            raise AssessmentOutputError('評価AIの応答が不完全なJSON形式のため読み取れませんでした。結果は保存されていません。') from exc
    finally:
        await oaw.delete_thread_by_id(thread)


def row_dict(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def assessment_settings(db, model, prompt_version=None):
    from modelPrompt import PromptTemplateService
    if not model:
        raise AssessmentConfigurationError('評価モデルが設定されていません。')
    service = PromptTemplateService(db)
    template = (service.get_template_by_version('evaluator', prompt_version)
                if prompt_version is not None else service.get_active_template('evaluator'))
    if template is None:
        raise AssessmentConfigurationError('評価プロンプトが見つかりません。プロンプト管理で設定を確認してください。')
    if any(name in template.prompt_text for name in ('submit_irt_judgments', 'submit_debriefing_report')):
        raise AssessmentConfigurationError(
            f'評価プロンプトv{template.version}は旧形式です。'
            'プロンプト管理で三段階採点（○/△/×）に対応した評価プロンプトを有効にしてください。')
    return dict(prompt_type=template.template_type, prompt_id=template.id,
                prompt_version=template.version, instructions=template.prompt_text, model=model)


def load_input(db, session_id):
    from modelDatabase import ChatLog
    from modelSession import Session
    from modelIRT import IRTPatientInstance
    session = db.query(Session).filter_by(session_id=session_id).one()
    items = db.query(IRTPatientInstance).filter_by(patient_id=session.patient_id).all()
    logs = db.query(ChatLog).filter_by(session_id=session_id).order_by(ChatLog.created_at, ChatLog.id).all()
    # Original injected scenario, not today's mutable Drive data. Never use evaluation reports as context.
    context = '\n'.join(l.message for l in logs if l.sender == 'System' and l.is_initial_message
                        and '調査開始時点で開示されている情報:' in l.message)
    return make_input(row_dict(session), [row_dict(i) for i in items], [row_dict(l) for l in logs], context)


def get_saved(db, session_id):
    from modelIRT import IRTAssessmentRun
    # Reuse saved evidence across the three-grade migration instead of silently calling the LLM again.
    return db.query(IRTAssessmentRun).filter(
        IRTAssessmentRun.session_id == session_id,
        IRTAssessmentRun.rubric_version.in_(['intent-1', ASSESSMENT_SCHEMA_VERSION])).order_by(
        IRTAssessmentRun.created_at.desc(), IRTAssessmentRun.id.desc()).first()


def saved_result(run):
    document = json.loads(run.result_json)
    # Restore the model's original grade, not a previous validator's automatic pending fallback.
    raw = document.get('model_output', document.get('assessment', document))
    payload = json.loads(run.input_json)
    if payload.get('schema_version') == 'intent-1':
        for judgment in raw['judgments']:
            if judgment['grade'] == 'pending':
                # An old uncertain result cannot establish the required fact. Do not invent evidence.
                judgment['grade'] = 'missing'
                judgment['confidence'] = 0.0
                judgment['reason'] = '旧評価では項目に必要な事実を確認できていないため×。旧評価理由：' + judgment['reason']
    return summarize(raw, payload)


async def ensure_assessment(db, session_id, oaw, evaluator_model=None, prompt_version=None, force=False):
    from modelIRT import IRTAssessmentRun
    # PostgreSQL transaction advisory lock also coordinates separate worker processes.
    # A dedicated session is used by the caller, so legacy request transactions stay untouched.
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy import text
        for _ in range(600):
            if db.execute(text('SELECT pg_try_advisory_xact_lock(hashtext(:key))'),
                          {'key': f'{ASSESSMENT_SCHEMA_VERSION}:{session_id}'}).scalar():
                break
            await asyncio.sleep(0.1)
        else:
            db.rollback()
            raise TimeoutError('Assessment already running')
    existing = get_saved(db, session_id)
    if existing and not force:
        settings = json.loads(existing.input_json).get('assessment', {})
        if prompt_version is not None and (settings.get('prompt_version') != prompt_version
                                           or settings.get('model') != evaluator_model):
            raise ValueError('Saved assessment uses different settings; it will not be overwritten')
        db.rollback()
        return saved_result(existing)
    payload = load_input(db, session_id)
    payload['assessment'] = assessment_settings(db, evaluator_model, prompt_version)
    raw = await assess(oaw, payload)
    try:
        validated = validate_assessment(raw, payload)
    except ValueError as exc:
        raise AssessmentOutputError(
            '評価AIの応答に項目の欠落や発言分類の不整合があり、採点結果を確定できませんでした。結果は保存されていません。') from exc
    changed = [j['instance_id'] for j, original in zip(validated['judgments'], raw['judgments']) if j != original]
    if changed:
        logging.warning('Assessment evidence normalized: session=%s item_ids=%s', session_id, changed)
    run = IRTAssessmentRun(id=str(uuid.uuid4()), session_id=session_id, rubric_version=ASSESSMENT_SCHEMA_VERSION,
                           evaluator_model=evaluator_model, input_hash=input_hash(payload),
                           input_json=json.dumps(payload, ensure_ascii=False),
                           result_json=json.dumps(dict(assessment=validated, model_output=raw), ensure_ascii=False))
    db.add(run)
    db.commit()
    return summarize(validated, payload)
