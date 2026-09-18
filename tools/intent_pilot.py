"""Bounded, resumable offline pilot. Default is a cost preview; never writes to the DB."""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from intent_assessment import TOOL, input_hash, make_input, summarize
from intent_assessment_service import assess, MAX_OUTPUT_TOKENS
from openai_assistant import OpenAIAssistantWrapper


def payloads(snapshot):
    for session in snapshot['sessions']:
        logs = [l for l in snapshot['logs'] if l['session_id'] == session['session_id']]
        context = '\n'.join(l['message'] for l in logs if l['sender'] == 'System'
                            and l['is_initial_message'] and '調査開始時点で開示されている情報:' in l['message'])
        items = [i for i in snapshot['items'] if i['patient_id'] == session['patient_id']]
        yield make_input(session, items, logs, context)


def cost_bound(payload):
    # UTF-8 byte count is a deliberately conservative token upper bound, plus framing allowance.
    raw = json.dumps(dict(input=payload, tools=[TOOL]), ensure_ascii=False)
    upper_input_tokens = len(raw.encode('utf-8')) + 2048
    return upper_input_tokens * 2.5 / 1_000_000 + MAX_OUTPUT_TOKENS * 15 / 1_000_000


async def run(args):
    source = json.loads(args.snapshot.read_text(encoding='utf-8'))
    inputs = list(payloads(source))
    prompt = json.loads(args.prompt.read_text(encoding='utf-8'))
    for payload in inputs:
        payload['assessment'] = dict(prompt_type=prompt['template_type'], instructions=prompt['prompt_text'], model=args.model)
    prior = [] if not args.output.exists() else [json.loads(line) for line in args.output.read_text(encoding='utf-8').splitlines()]
    hashes = {r['input_hash'] for r in prior}
    # A changed prompt must not silently repeat sessions from an existing experiment.
    seen_sessions = {r['session_id'] for r in prior}
    if args.retry_failed_session:
        failures = [r for r in prior if r['state'] == 'failed' and r['session_id'] == args.retry_failed_session]
        if not failures or any(r['state'] == 'completed' and r['session_id'] == args.retry_failed_session for r in prior):
            raise ValueError('Explicit retry requires a failed, not completed session')
        hashes.discard(failures[-1]['input_hash'])
        seen_sessions.discard(args.retry_failed_session)
    pending = [p for p in inputs if input_hash(p) not in hashes
               and p['session_id'] not in seen_sessions][:args.limit]
    reserved = sum(r['reserved_usd'] for r in prior if r['state'] == 'started')
    bound = sum(cost_bound(p) for p in pending)
    print(json.dumps(dict(model=args.model, remaining_calls=len(pending), reserved_usd=round(reserved, 4),
                          additional_upper_usd=round(bound, 4), budget_usd=args.budget_usd)), flush=True)
    if not args.execute:
        return
    if reserved + bound > args.budget_usd:
        raise ValueError('Pilot would exceed total reserved budget')
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    config = json.loads((root / 'conf.json').read_text(encoding='utf-8'))
    oaw = OpenAIAssistantWrapper(SimpleNamespace(**config))
    oaw.client = oaw.client.with_options(max_retries=0, timeout=120)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def append(record):
        with args.output.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
            f.flush()
    for payload in pending:
        key = input_hash(payload)
        # Reserve BEFORE the request; interrupted/uncertain calls will never be repeated automatically.
        append(dict(state='started', input_hash=key, session_id=payload['session_id'], reserved_usd=cost_bound(payload)))
        try:
            raw = await assess(oaw, payload)
            summary = summarize(raw, payload)
            append(dict(state='completed', input_hash=key, session_id=payload['session_id'],
                        reserved_usd=0, input=payload, result=raw, summary=summary))
            print(json.dumps(dict(session_id=payload['session_id'], grade_counts={k: summary[k] for k in
                                  ('collected_item_count','incidental_item_count','missing_item_count')})), flush=True)
        except Exception as exc:
            append(dict(state='failed', input_hash=key, session_id=payload['session_id'], reserved_usd=0,
                        error_type=type(exc).__name__, reason=str(exc) if isinstance(exc, ValueError) else 'Request failed'))
            raise RuntimeError('Pilot stopped after failure: ' + type(exc).__name__) from None


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt', type=Path, required=True, help='Frozen reviewed prompt export; never a runtime fallback')
    parser.add_argument('--model', default='gpt-5.4', choices=['gpt-5.4'], help='Model covered by this experiment cost estimate')
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--budget-usd', type=float, default=8)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--retry-failed-session')
    asyncio.run(run(parser.parse_args()))
