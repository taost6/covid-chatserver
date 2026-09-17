"""Feedback audit input export. SELECT-only, repeatable-read transaction; no LLM calls."""
import argparse
import csv
import json
import os
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


def export(output):
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    suffix = os.environ.get('TABLE_SUFFIX', '')
    if suffix not in ('', '_stg'):
        raise ValueError('Unexpected TABLE_SUFFIX')
    with (root / 'doc/human_vs_ai_v12_comparison_20260824.csv').open(encoding='utf-8-sig', newline='') as f:
        humans = [r for r in csv.DictReader(f) if r.get('患者ID')]
    human_ids = [r['会話履歴'].rsplit('/', 1)[-1] for r in humans]
    if len(human_ids) != 10 or len(set(human_ids)) != 10:
        raise ValueError('Expected ten distinct human sessions')
    conn = psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require', connect_timeout=15,
                            cursor_factory=RealDictCursor)
    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            def query(statement, table, args=()):
                cur.execute(sql.SQL(statement).format(sql.Identifier(table)), args)
                return [dict(row) for row in cur.fetchall()]
            items = query('SELECT * FROM {} ORDER BY patient_id, id', 'irt_patient_instances' + suffix)
            types = query('SELECT * FROM {} ORDER BY catalog_version, code', 'irt_item_types' + suffix)
            prompts = query('SELECT * FROM {} WHERE is_active OR version = 12 ORDER BY template_type, version', 'prompt_templates')
            sessions = query('SELECT * FROM {} WHERE session_id = ANY(%s)', 'sessions' + suffix, (human_ids,))
            candidates = query("""SELECT * FROM {} WHERE patient_id IN ('60','61','62','63')
                AND user_name = 'IRT_Batch' AND status = 'completed'
                AND patient_model = 'gpt-4.1' AND evaluator_model = 'gpt-5.4'
                AND interviewer_model IN ('gpt-4.1','gpt-5.2')
                AND interviewer_version BETWEEN 10 AND 14
                ORDER BY patient_id, interviewer_model, interviewer_version, session_id""", 'sessions' + suffix)
            # Ten reproducible pilot candidates: both models per patient, plus different prompt versions.
            pilot = []
            for patient in ('60','61','62','63'):
                for model in ('gpt-4.1','gpt-5.2'):
                    pool = [s for s in candidates if s['patient_id'] == patient and s['interviewer_model'] == model]
                    if pool:
                        pilot.append(pool[0 if model == 'gpt-4.1' else -1])
            for patient in ('60','61'):
                pool = [s for s in candidates if s['patient_id'] == patient and s['interviewer_version'] == 12
                        and s['session_id'] not in {p['session_id'] for p in pilot}]
                if pool:
                    pilot.append(pool[0])
            ids = human_ids + [s['session_id'] for s in pilot]
            logs = query('SELECT * FROM {} WHERE session_id = ANY(%s) ORDER BY session_id, created_at, id', 'chat_logs' + suffix, (ids,))
            judgments = query('SELECT * FROM {} WHERE session_id = ANY(%s) ORDER BY session_id, instance_id, id', 'irt_response_judgments' + suffix, (ids,))
            result = dict(table_suffix=suffix, human_order=human_ids, sessions=sessions + pilot,
                          ai_candidates=candidates, items=items, item_types=types, prompts=prompts,
                          logs=logs, judgments=judgments)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite the source snapshot of an earlier audit.
        with output.open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, default=str, indent=2)
        print(json.dumps(dict(table_suffix=suffix, humans=len(sessions), pilot_ai=len(pilot),
                              candidates=len(candidates), items=len(items), logs=len(logs), output=str(output))))
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.output)
    except Exception as exc:
        # Avoid credentials/connection strings in terminal errors.
        print('Snapshot failed: ' + type(exc).__name__)
        raise SystemExit(1)
