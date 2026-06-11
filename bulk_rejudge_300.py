"""
300セッション一括再判定スクリプト

対象: 患者1〜10 × 保健師AI(gpt-4.1/gpt-5.2) × プロンプトv10〜14 × 3反復 = 300セッション
各セッションの対話ログを、固定条件（gpt-5.4 × 評価者プロンプト固定版 × 現時点の項目定義）で
3回判定し、項目ごとに多数決をとる。

フェーズ1（judge）: 判定のみ実行し、結果をJSONLチェックポイントに保存（DB書き込みなし）
  DATABASE_URL=... python bulk_rejudge_300.py [--concurrency 8] [--votes 3]

フェーズ2（apply）: チェックポイントから多数決を集計し、既存判定をバックアップした上でDBを更新
  DATABASE_URL=... python bulk_rejudge_300.py --apply

中断・再開可: 完了済みセッションはチェックポイントから自動スキップ
"""
import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import psycopg2
import psycopg2.extras

from chatconf import ChatConfigModel
from modelUserDef import AssistantDef
from openai_assistant import OpenAIAssistantWrapper
from judge_reproducibility_test import (
    IRT_JUDGMENT_TOOL, split_text_for_prompt, run_one_judgment,
)

JST = timezone(timedelta(hours=9))
SUFFIX = os.environ.get("TABLE_SUFFIX", "_stg")
EVALUATOR_MODEL = "gpt-5.4"
CHECKPOINT = "bulk_rejudge_checkpoint.jsonl"
BACKUP_PREFIX = "judgments_backup_before_rejudge"


def get_conn():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL is not set")
    return psycopg2.connect(db_url, sslmode='require',
                            cursor_factory=psycopg2.extras.RealDictCursor)


def select_target_sessions(cur, models, ver_min, ver_max):
    cur.execute(f"""
        SELECT session_id, patient_id, interviewer_model, interviewer_version
        FROM sessions{SUFFIX} s
        WHERE s.patient_id ~ '^[0-9]+$' AND s.patient_id::int BETWEEN 1 AND 10
          AND s.interviewer_version BETWEEN %s AND %s
          AND s.evaluator_model = %s AND s.status = 'completed'
          AND s.interviewer_model = ANY(%s)
          AND s.patient_model = 'gpt-4.1' AND s.user_name = 'IRT_Batch'
        ORDER BY s.patient_id::int, s.interviewer_model, s.interviewer_version, s.created_at
    """, (ver_min, ver_max, EVALUATOR_MODEL, models))
    return [dict(r) for r in cur.fetchall()]


def fetch_evaluator_template(cur):
    """アクティブな評価者プロンプトを1度だけ解決し、以後この版に固定する"""
    cur.execute("""
        SELECT version, prompt_text FROM prompt_templates
        WHERE template_type = 'evaluator' AND is_active = TRUE
        ORDER BY version DESC LIMIT 1
    """)
    tmpl = cur.fetchone()
    if tmpl is None:
        sys.exit("No active evaluator prompt template")
    return tmpl["version"], tmpl["prompt_text"]


def fetch_instances(cur, patient_id):
    """現時点の項目定義（凍結スナップショットとしてチェックポイントにも保存）"""
    cur.execute(f"""
        SELECT id, item_type_code, instance_number, description
        FROM irt_patient_instances{SUFFIX}
        WHERE patient_id = %s AND is_detectable = TRUE
        ORDER BY item_type_code, instance_number
    """, (patient_id,))
    return [dict(r) for r in cur.fetchall()]


def build_full_prompt(cur, session_id, instances, evaluator_prompt_text):
    cur.execute(f"""
        SELECT ai_role, user_role, message FROM chat_logs{SUFFIX}
        WHERE session_id = %s AND sender IN ('User', 'Assistant')
          AND is_initial_message = FALSE
        ORDER BY created_at
    """, (session_id,))
    logs = cur.fetchall()
    if not logs:
        raise RuntimeError(f"No chat logs for session {session_id}")
    conversation_history = "\n".join(
        f"{r['ai_role'] or r['user_role']}: {r['message']}"
        for r in logs
        if r['message'] and not r['message'].startswith("Debriefing Data:")
    )
    instances_text = "\n".join(
        f"- ID:{r['id']} [{r['item_type_code']}] {r['description'] or ''}"
        for r in instances
    )
    return (
        f"{evaluator_prompt_text}\n\n"
        f"【判定対象のIRT項目一覧】\n{instances_text}\n\n"
        f"【対話履歴】\n{conversation_history}\n\n"
        f"上記の対話履歴を分析し、各IRT項目について submit_irt_judgments 関数を呼び出して判定結果を提出してください。"
    )


def load_checkpoint(path):
    done = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                done[rec["session_id"]] = rec
    return done


async def judge_phase(args):
    conn = get_conn()
    cur = conn.cursor()
    sessions = select_target_sessions(cur, args.models.split(","), *args.versions)
    eval_ver, eval_text = fetch_evaluator_template(cur)
    print(f"target sessions: {len(sessions)} | evaluator: {EVALUATOR_MODEL} "
          f"x prompt v{eval_ver} x {args.votes} votes")

    done = load_checkpoint(args.checkpoint)
    todo = [s for s in sessions if s["session_id"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"checkpoint: {len(done)} done, {len(todo)} to go "
          f"(= {len(todo) * args.votes} judgment calls)")
    if not todo:
        print("All sessions already judged. Run with --apply to update DB.")
        return

    # プロンプトと項目スナップショットを準備（DBアクセスはここで完結）
    instances_by_patient = {}
    prepared = []
    for s in todo:
        pid = s["patient_id"]
        if pid not in instances_by_patient:
            instances_by_patient[pid] = fetch_instances(cur, pid)
        instances = instances_by_patient[pid]
        prompt = build_full_prompt(cur, s["session_id"], instances, eval_text)
        prepared.append((s, instances, prompt))
    conn.close()

    config = ChatConfigModel(**json.load(open("conf.json")))
    oaw = OpenAIAssistantWrapper(config)
    with open("assistants.json") as f:
        assistants = json.load(f)
    evaluator_assistant_id = assistants[2]

    sem = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    counter = {"done": 0, "failed": 0}

    async def one_vote(prompt, valid_ids, label):
        async with sem:
            return await run_one_judgment(oaw, evaluator_assistant_id, prompt,
                                          valid_ids, label)

    async def process_session(s, instances, prompt):
        sid = s["session_id"]
        valid_ids = {r["id"] for r in instances}
        label_base = f"p{s['patient_id']}/{s['interviewer_model']}/v{s['interviewer_version']}"
        votes = []
        for v in range(args.votes):
            try:
                j = await one_vote(prompt, valid_ids, f"{label_base}/vote{v + 1}")
                votes.append({"ok": True,
                              "judgments": {str(k): val for k, val in j.items()}})
            except Exception as e:
                votes.append({"ok": False, "error": str(e)})
        ok_votes = [v for v in votes if v["ok"]]
        rec = {
            "session_id": sid,
            "patient_id": s["patient_id"],
            "interviewer_model": s["interviewer_model"],
            "interviewer_version": s["interviewer_version"],
            "evaluator_model": EVALUATOR_MODEL,
            "evaluator_prompt_version": eval_ver,
            "judged_at": datetime.now(JST).isoformat(),
            "instances_snapshot": instances,
            "votes": votes,
        }
        async with write_lock:
            if len(ok_votes) == args.votes:
                with open(args.checkpoint, "a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                counter["done"] += 1
            else:
                # 失敗票があるセッションはチェックポイントに書かず、再実行で拾い直す
                counter["failed"] += 1
                with open("bulk_rejudge_failures.jsonl", "a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total = counter["done"] + counter["failed"]
            print(f"[{total}/{len(todo)}] {label_base} "
                  f"{'OK' if len(ok_votes) == args.votes else 'FAILED'} "
                  f"(done={counter['done']} failed={counter['failed']})")

    await asyncio.gather(*[process_session(*p) for p in prepared])
    print(f"\njudge phase finished: done={counter['done']} failed={counter['failed']}")
    if counter["failed"]:
        print("Failed sessions were NOT checkpointed. Re-run the same command to retry them.")
    else:
        print(f"All done. Review results, then run with --apply to update DB.")


def majority(vote_values):
    k = sum(1 for v in vote_values if v["is_correct"])
    n = len(vote_values)
    is_correct = k * 2 > n
    side = [v for v in vote_values if v["is_correct"] == is_correct]
    conf = sum((v.get("confidence") or 0) for v in side) / len(side) if side else None
    return is_correct, k, n, conf


def apply_phase(args):
    done = load_checkpoint(args.checkpoint)
    if not done:
        sys.exit(f"No checkpoint found ({args.checkpoint}). Run judge phase first.")

    conn = get_conn()
    cur = conn.cursor()
    sessions = select_target_sessions(cur, args.models.split(","), *args.versions)
    missing = [s["session_id"] for s in sessions if s["session_id"] not in done]
    if missing:
        sys.exit(f"{len(missing)} target sessions not yet judged. Finish judge phase first.")

    session_ids = [s["session_id"] for s in sessions]

    # バックアップ
    cur.execute(f"""
        SELECT * FROM irt_response_judgments{SUFFIX}
        WHERE session_id = ANY(%s)
    """, (session_ids,))
    old = [dict(r) for r in cur.fetchall()]
    for r in old:
        if r.get("judged_at"):
            r["judged_at"] = r["judged_at"].isoformat()
    backup_path = f"{BACKUP_PREFIX}_{datetime.now(JST).strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_path, "w") as f:
        json.dump(old, f, ensure_ascii=False, indent=1)
    print(f"backed up {len(old)} existing judgments -> {backup_path}")

    # 差し替え
    inserted = 0
    cur2 = conn.cursor()
    for sid in session_ids:
        rec = done[sid]
        valid_ids = [r["id"] for r in rec["instances_snapshot"]]
        rows = []
        for iid in valid_ids:
            vote_values = [v["judgments"][str(iid)] for v in rec["votes"]
                           if v["ok"] and str(iid) in v["judgments"]]
            if not vote_values:
                continue
            is_correct, k, n, conf = majority(vote_values)
            rows.append((sid, iid, is_correct, 'ai', conf,
                         rec["evaluator_model"], rec["evaluator_prompt_version"],
                         n, k, rec["judged_at"]))
        cur2.execute(f"DELETE FROM irt_response_judgments{SUFFIX} WHERE session_id = %s", (sid,))
        psycopg2.extras.execute_values(cur2, f"""
            INSERT INTO irt_response_judgments{SUFFIX}
            (session_id, instance_id, is_correct, judgment_method, confidence,
             evaluator_model, evaluator_prompt_version, votes_total, votes_correct, judged_at)
            VALUES %s
        """, rows)
        inserted += len(rows)
    conn.commit()
    print(f"replaced judgments for {len(session_ids)} sessions ({inserted} rows)")
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None,
                    help="処理セッション数の上限（動作確認用）")
    ap.add_argument("--models", default="gpt-4.1,gpt-5.2",
                    help="対象の保健師AIモデル（カンマ区切り）")
    ap.add_argument("--versions", type=int, nargs=2, default=[10, 14],
                    metavar=("MIN", "MAX"), help="対象の保健師プロンプトバージョン範囲")
    ap.add_argument("--checkpoint", default=CHECKPOINT,
                    help="チェックポイントファイルのパス")
    ap.add_argument("--apply", action="store_true",
                    help="チェックポイントの多数決結果をDBに反映（要バックアップ確認）")
    args = ap.parse_args()
    if args.apply:
        apply_phase(args)
    else:
        asyncio.run(judge_phase(args))


if __name__ == "__main__":
    main()
