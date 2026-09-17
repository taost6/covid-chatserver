"""One assessment path for interactive requests and offline/batch pilots."""
import asyncio
import json
import uuid

from intent_assessment import ASSESSMENT_SCHEMA_VERSION, TOOL, input_hash, make_input, summarize, validate_assessment
from modelUserDef import AssistantDef

MAX_OUTPUT_TOKENS = 10000


async def assess(oaw, payload):
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
            raise ValueError('No intent assessment returned')
        return validate_assessment(json.loads(call.arguments), payload)
    finally:
        await oaw.delete_thread_by_id(thread)


def row_dict(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def assessment_settings(db, model, prompt_version=None):
    from modelPrompt import PromptTemplateService
    if not model:
        raise ValueError('An evaluator model must be selected')
    service = PromptTemplateService(db)
    template = (service.get_template_by_version('evaluator', prompt_version)
                if prompt_version is not None else service.get_active_template('evaluator'))
    if template is None:
        raise ValueError('Evaluator prompt not found')
    if any(name in template.prompt_text for name in ('submit_irt_judgments', 'submit_debriefing_report')):
        raise ValueError('Selected evaluator prompt uses a retired output format; activate the updated evaluator')
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
    return db.query(IRTAssessmentRun).filter_by(session_id=session_id, rubric_version=ASSESSMENT_SCHEMA_VERSION).order_by(
        IRTAssessmentRun.created_at.desc(), IRTAssessmentRun.id.desc()).first()


def saved_result(run):
    return summarize(json.loads(run.result_json), json.loads(run.input_json))


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
    raw = validate_assessment(raw, payload)
    run = IRTAssessmentRun(id=str(uuid.uuid4()), session_id=session_id, rubric_version=ASSESSMENT_SCHEMA_VERSION,
                           evaluator_model=evaluator_model, input_hash=input_hash(payload),
                           input_json=json.dumps(payload, ensure_ascii=False),
                           result_json=json.dumps(raw, ensure_ascii=False))
    db.add(run)
    db.commit()
    return summarize(raw, payload)
