"""
IRT バッチ実行エンジン
ヘッドレス（WebSocket不要）でAI対話を実行し、完了後にIRT正誤判定を行う。
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from modelUserDef import AssistantDef
from modelRole import PatientRoleProvider
from modelSession import Session as SessionModel
from modelPrompt import PromptTemplateService
from openai_assistant import OpenAIAssistantWrapper
from ai_conversation_manager import get_id, log_message
import modelDatabase

logger = logging.getLogger(__name__)

# JST timezone
JST = timezone(timedelta(hours=9))


class HeadlessConversation:
    """WebSocket不要のAI対話実行"""

    MAX_TURNS = 100

    def __init__(self, oaw: OpenAIAssistantWrapper, role_provider: PatientRoleProvider, db,
                 nurse_model: Optional[str] = None, patient_model: Optional[str] = None,
                 patient_prompt_version: Optional[int] = None,
                 interviewer_prompt_version: Optional[int] = None):
        self.oaw = oaw
        self.role_provider = role_provider
        self.db = db
        self.nurse_model = nurse_model
        self.patient_model = patient_model
        self.patient_prompt_version = patient_prompt_version
        self.interviewer_prompt_version = interviewer_prompt_version

    async def run(self, patient_id: str, session_id: str) -> dict:
        """1セッション分の対話を実行して結果を返す"""
        nurse_thread_id = None
        patient_thread_id = None

        try:
            # 1. assistants.json から AI ID 取得
            with open("assistants.json", "r") as f:
                assistants = json.load(f)
            if len(assistants) < 2:
                raise RuntimeError("Insufficient assistant IDs in assistants.json")

            # 2. スレッド作成
            nurse_thread_id = await self.oaw.create_thread()
            patient_thread_id = await self.oaw.create_thread()

            nurse_ai = AssistantDef(
                user_id=get_id(), role="保健師",
                assistant_id=assistants[1], thread_id=nurse_thread_id
            )
            patient_ai = AssistantDef(
                user_id=get_id(), role="患者",
                assistant_id=assistants[0], thread_id=patient_thread_id
            )

            # 3. プロンプト設定
            patient_chunks, interview_date_str = self.role_provider.get_patient_prompt_chunks(
                patient_id, prompt_version=self.patient_prompt_version
            )
            for chunk in patient_chunks:
                await self.oaw.add_message_to_thread(patient_ai.thread_id, chunk)
                await log_message(
                    self.db, session_id, "System", patient_id,
                    "患者", "System", chunk, logger
                )

            # 患者AI初期メッセージ
            patient_details = self.role_provider.get_patient_details(patient_id)
            patient_name = patient_details.get("name", "名無し")
            try:
                prompt_db = modelDatabase.PromptSessionLocal()
                prompt_service = PromptTemplateService(prompt_db)
                if self.patient_prompt_version is not None:
                    patient_template = prompt_service.get_template_by_version('patient', self.patient_prompt_version)
                else:
                    patient_template = prompt_service.get_active_template('patient')
                prompt_db.close()
                if patient_template and patient_template.message_text:
                    initial_patient_message = patient_template.message_text.replace('{patient_name}', patient_name)
                else:
                    initial_patient_message = f"私の名前は{patient_name}です。何でも聞いてください。"
            except Exception:
                initial_patient_message = f"私の名前は{patient_name}です。何でも聞いてください。"

            await log_message(
                self.db, session_id, "AI", patient_id,
                "傍聴者", "Assistant", initial_patient_message, logger,
                is_initial_message=True, ai_role="患者"
            )

            # 保健師AIプロンプト設定
            interviewer_chunks, initial_nurse_message = self.role_provider.get_interviewer_prompt_chunks(
                interview_date_str, prompt_version=self.interviewer_prompt_version
            )
            for chunk in interviewer_chunks:
                await self.oaw.add_message_to_thread(nurse_ai.thread_id, chunk)
                await log_message(
                    self.db, session_id, "System", "N/A",
                    "保健師", "System", chunk, logger
                )

            await log_message(
                self.db, session_id, "AI", nurse_ai.assistant_id,
                "傍聴者", "Assistant", initial_nurse_message, logger,
                is_initial_message=False, ai_role="保健師"
            )

            # 4. 対話ループ
            # 保健師AI用の会話終了ツール定義
            # フロー: 保健師が感謝の言葉+ツール呼び出しで終了を宣言
            #       → 感謝テキストを患者AIに送信 → 患者が応答 → 終了
            end_conversation_tool = {
                "type": "function",
                "name": "end_conversation_and_start_debriefing",
                "description": "聞き取り調査が十分に完了したと判断した場合に呼び出す。"
                               "感謝の言葉と一緒に呼び出すこと。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                }
            }

            history: List[Dict[str, str]] = [
                {"role": "患者", "text": initial_patient_message},
                {"role": "保健師", "text": initial_nurse_message},
            ]
            current_turn = "patient"  # 保健師が初期メッセージ送信済みなので患者から
            turn_count = 0
            ended_by = "max_turns"

            while turn_count < self.MAX_TURNS:
                current_ai = nurse_ai if current_turn == "nurse" else patient_ai

                # 直前の相手メッセージを取得
                last_message = None
                for msg in reversed(history):
                    if msg["role"] != current_ai.role:
                        last_message = msg["text"]
                        break

                if not last_message:
                    break

                current_model = self.patient_model if current_ai.role == "患者" else self.nurse_model
                response_msg, tool_call = await self.oaw.send_message(
                    current_ai, last_message,
                    tools=[] if current_ai.role == "患者" else [end_conversation_tool],
                    max_retries=5,
                    model=current_model
                )

                if tool_call and tool_call.name == "end_conversation_and_start_debriefing":
                    # 保健師AIが終了を判断した
                    # 付随テキスト（感謝の言葉）があれば患者に送って応答を得る
                    if response_msg and not response_msg.startswith("FAILED:"):
                        cleaned = response_msg.strip()
                        if len(cleaned) >= 3:
                            history.append({"role": nurse_ai.role, "text": cleaned})
                            await log_message(
                                self.db, session_id, "AI", nurse_ai.assistant_id,
                                "傍聴者", "Assistant", cleaned, logger,
                                ai_role="保健師"
                            )
                            turn_count += 1

                            # 患者AIに最後の応答機会を与える
                            patient_response, _ = await self.oaw.send_message(
                                patient_ai, cleaned, tools=[],
                                max_retries=5, model=self.patient_model
                            )
                            if patient_response and not patient_response.startswith("FAILED:"):
                                patient_cleaned = patient_response.strip()
                                if len(patient_cleaned) >= 3:
                                    history.append({"role": patient_ai.role, "text": patient_cleaned})
                                    await log_message(
                                        self.db, session_id, "AI", patient_ai.assistant_id,
                                        "傍聴者", "Assistant", patient_cleaned, logger,
                                        ai_role="患者"
                                    )
                                    turn_count += 1

                    ended_by = "tool_call"
                    logger.info(f"[Batch] Session {session_id}: conversation ended by nurse tool_call at turn {turn_count}")
                    break

                if response_msg and not response_msg.startswith("FAILED:"):
                    cleaned = response_msg.strip()
                    if len(cleaned) < 3:
                        continue

                    history.append({"role": current_ai.role, "text": cleaned})
                    await log_message(
                        self.db, session_id, "AI", current_ai.assistant_id,
                        "傍聴者", "Assistant", cleaned, logger,
                        ai_role=current_ai.role
                    )
                    turn_count += 1
                    current_turn = "patient" if current_turn == "nurse" else "nurse"
                else:
                    # API呼び出しがリトライ上限まで失敗した場合はセッションを失敗として扱う。
                    # ここで正常終了扱いにすると「挨拶のみの対話が completed になり全問不正解で
                    # 判定される」データ汚染が起きる（2026-06-19/20に17件発生した実績あり）。
                    raise RuntimeError(f"[Batch] Session {session_id}: AI response failed after retries: {response_msg}")

            # 5. スレッド削除
            return {
                "session_id": session_id,
                "turn_count": turn_count,
                "ended_by": ended_by,
                "interview_date": interview_date_str,
            }

        finally:
            # 確実にスレッド削除
            for tid in [nurse_thread_id, patient_thread_id]:
                if tid:
                    try:
                        await self.oaw.delete_thread_by_id(tid)
                    except Exception as e:
                        logger.warning(f"Failed to delete thread {tid}: {e}")


class IRTBatchRunner:
    """バッチ実行管理"""

    def __init__(self, oaw: OpenAIAssistantWrapper, role_provider: PatientRoleProvider):
        self.oaw = oaw
        self.role_provider = role_provider
        self.batches: Dict[str, dict] = {}  # batch_id -> state
        self.conversation_timeout_seconds = int(os.getenv("IRT_CONVERSATION_TIMEOUT_SECONDS", "1800"))
        self.judgment_timeout_seconds = int(os.getenv("IRT_JUDGMENT_TIMEOUT_SECONDS", "1200"))

    async def start_batch(self, patient_ids: List[str], runs_per_patient: int, concurrency: int,
                          nurse_model: Optional[str] = None, patient_model: Optional[str] = None,
                          evaluator_model: Optional[str] = None,
                          patient_prompt_version: Optional[int] = None,
                          interviewer_prompt_version: Optional[int] = None,
                          evaluator_prompt_version: Optional[int] = None) -> str:
        # Resolve and validate the single evaluator before starting paid conversations.
        from intent_assessment_service import assessment_settings
        prompt_db = modelDatabase.PromptSessionLocal()
        try:
            settings = assessment_settings(prompt_db, evaluator_model, evaluator_prompt_version)
            evaluator_prompt_version = settings['prompt_version']
        finally:
            prompt_db.close()
        batch_id = get_id()
        total = len(patient_ids) * runs_per_patient

        state = {
            "batch_id": batch_id,
            "status": "running",
            "total": total,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "results": [],
            "task": None,
            "cancel_event": asyncio.Event(),
            "nurse_model": nurse_model,
            "patient_model": patient_model,
            "evaluator_model": evaluator_model,
            "patient_prompt_version": patient_prompt_version,
            "interviewer_prompt_version": interviewer_prompt_version,
            "evaluator_prompt_version": evaluator_prompt_version,
        }
        self.batches[batch_id] = state

        state["task"] = asyncio.create_task(
            self._run_batch(batch_id, patient_ids, runs_per_patient, concurrency)
        )
        state["task"].add_done_callback(lambda task: self._finalize_batch_task(batch_id, task))
        return batch_id

    def _mark_running_entries(self, state: dict, status: str, error: str):
        for entry in state["results"]:
            if entry.get("status") == "running":
                entry["status"] = status
                entry["error"] = error
                entry["phase"] = entry.get("phase") or "unknown"
        state["running"] = 0

    def _finalize_batch_task(self, batch_id: str, task: asyncio.Task):
        state = self.batches.get(batch_id)
        if not state:
            return
        if state["status"] in ("completed", "stopped", "failed"):
            return

        try:
            exc = task.exception()
        except asyncio.CancelledError:
            state["status"] = "stopped"
            self._mark_running_entries(state, "cancelled", "Batch task was cancelled")
            return

        if exc:
            state["status"] = "failed"
            self._mark_running_entries(state, "failed", f"Batch task crashed: {exc}")
            logger.error(
                f"[Batch {batch_id}] Batch task crashed: {exc}",
                exc_info=(type(exc), exc, exc.__traceback__)
            )

    async def _run_batch(self, batch_id: str, patient_ids: List[str], runs_per_patient: int, concurrency: int):
        state = self.batches[batch_id]
        sem = asyncio.Semaphore(concurrency)

        async def run_one(patient_id: str, run_number: int):
            if state["cancel_event"].is_set():
                return

            async with sem:
                if state["cancel_event"].is_set():
                    return

                session_id = get_id()
                result_entry = {
                    "session_id": session_id,
                    "patient_id": patient_id,
                    "run_number": run_number,
                    "status": "running",
                    "phase": "queued",
                    "correct_count": None,
                    "total_count": None,
                    "error": None,
                }
                state["results"].append(result_entry)
                state["running"] += 1

                db = None
                db_session = None
                try:
                    result_entry["phase"] = "initializing"
                    db = modelDatabase.SessionLocal()

                    # セッションレコード作成
                    # プロンプトバージョン取得
                    prompt_db = modelDatabase.PromptSessionLocal()
                    prompt_service = PromptTemplateService(prompt_db)
                    p_ver = state.get("patient_prompt_version")
                    i_ver = state.get("interviewer_prompt_version")
                    if p_ver is not None:
                        patient_tmpl = prompt_service.get_template_by_version('patient', p_ver)
                    else:
                        patient_tmpl = prompt_service.get_active_template('patient')
                    if i_ver is not None:
                        interviewer_tmpl = prompt_service.get_template_by_version('interviewer', i_ver)
                    else:
                        interviewer_tmpl = prompt_service.get_active_template('interviewer')
                    # 評価者プロンプトもこの時点で解決し、セッションに記録・判定にも固定する
                    e_ver = state.get("evaluator_prompt_version")
                    if e_ver is not None:
                        evaluator_tmpl = prompt_service.get_template_by_version('evaluator', e_ver)
                    else:
                        evaluator_tmpl = prompt_service.get_active_template('evaluator')
                    resolved_evaluator_version = evaluator_tmpl.version if evaluator_tmpl else None
                    if evaluator_tmpl is None:
                        raise ValueError('Evaluator prompt not found')
                    prompt_db.close()

                    db_session = SessionModel(
                        session_id=session_id,
                        user_name="IRT_Batch",
                        user_role="傍聴者",
                        patient_id=patient_id,
                        status='active',
                        patient_version=patient_tmpl.version if patient_tmpl else None,
                        interviewer_version=interviewer_tmpl.version if interviewer_tmpl else None,
                        evaluator_version=resolved_evaluator_version,
                        patient_model=state["patient_model"],
                        interviewer_model=state["nurse_model"],
                        evaluator_model=state["evaluator_model"],
                    )
                    db.add(db_session)
                    db.commit()

                    # ヘッドレス対話実行
                    result_entry["phase"] = "conversation"
                    conv = HeadlessConversation(
                        self.oaw, self.role_provider, db,
                        nurse_model=state["nurse_model"],
                        patient_model=state["patient_model"],
                        patient_prompt_version=p_ver,
                        interviewer_prompt_version=i_ver,
                    )
                    conv_result = await asyncio.wait_for(
                        conv.run(patient_id, session_id),
                        timeout=self.conversation_timeout_seconds
                    )

                    # セッション完了
                    result_entry["phase"] = "conversation_completed"
                    db_session.status = 'completed'
                    db_session.completed_at = datetime.now(JST)
                    if conv_result.get("interview_date"):
                        db_session.interview_date = conv_result["interview_date"]
                    db.commit()

                    # IRT判定実行
                    result_entry["phase"] = "judgment"
                    judgment_result = await asyncio.wait_for(
                        self._execute_irt_judgment_for_batch(
                            session_id, db, evaluator_model=state["evaluator_model"],
                            evaluator_prompt_version=resolved_evaluator_version
                        ),
                        timeout=self.judgment_timeout_seconds
                    )

                    result_entry["status"] = "completed"
                    result_entry["phase"] = "completed"
                    result_entry["correct_count"] = judgment_result.get("correct_count", 0)
                    result_entry["total_count"] = judgment_result.get("total_count", 0)
                    result_entry["pending_item_count"] = judgment_result.get("pending_item_count", 0)
                    state["completed"] += 1

                    logger.info(
                        f"[Batch {batch_id}] patient={patient_id} run={run_number} "
                        f"session={session_id} turns={conv_result['turn_count']} "
                        f"ended_by={conv_result['ended_by']} "
                        f"correct={result_entry['correct_count']}/{result_entry['total_count']}"
                    )

                except asyncio.CancelledError:
                    result_entry["status"] = "cancelled"
                    result_entry["error"] = "Batch was cancelled"
                    logger.info(f"[Batch {batch_id}] Cancelled: patient={patient_id} run={run_number} session={session_id}")
                    raise
                except asyncio.TimeoutError:
                    error = (
                        f"Timeout during {result_entry.get('phase')} "
                        f"(conversation_timeout={self.conversation_timeout_seconds}s, "
                        f"judgment_timeout={self.judgment_timeout_seconds}s)"
                    )
                    logger.error(f"[Batch {batch_id}] {error}: patient={patient_id} run={run_number} session={session_id}")
                    result_entry["status"] = "failed"
                    result_entry["error"] = error
                    state["failed"] += 1
                    if db:
                        db.rollback()
                        if db_session:
                            try:
                                db_session.status = 'failed'
                                db_session.completed_at = datetime.now(JST)
                                db.commit()
                            except Exception:
                                db.rollback()
                except Exception as e:
                    logger.error(f"[Batch {batch_id}] Failed: patient={patient_id} run={run_number}: {e}")
                    result_entry["status"] = "failed"
                    result_entry["error"] = str(e)
                    state["failed"] += 1
                    if db:
                        db.rollback()
                        if db_session:
                            try:
                                db_session.status = 'failed'
                                db_session.completed_at = datetime.now(JST)
                                db.commit()
                            except Exception:
                                db.rollback()
                finally:
                    state["running"] = max(0, state["running"] - 1)
                    if db:
                        db.close()

        # タスクリスト生成
        tasks = []
        for pid in patient_ids:
            for run_num in range(1, runs_per_patient + 1):
                tasks.append(asyncio.create_task(run_one(pid, run_num)))

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            state["cancel_event"].set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._mark_running_entries(state, "cancelled", "Batch was cancelled")
            state["status"] = "stopped"
            logger.info(f"[Batch {batch_id}] Stopped by cancellation")
            return

        if state["cancel_event"].is_set():
            state["status"] = "stopped"
        else:
            state["status"] = "completed"

        logger.info(
            f"[Batch {batch_id}] Finished: "
            f"completed={state['completed']} failed={state['failed']} total={state['total']}"
        )

    async def _execute_irt_judgment_for_batch(self, session_id: str, db,
                                               evaluator_model: Optional[str] = None,
                                               evaluator_prompt_version: Optional[int] = None) -> dict:
        """Use the same evaluator as interactive sessions."""
        from intent_assessment_service import ensure_assessment
        result = await ensure_assessment(db, session_id, self.oaw, evaluator_model=evaluator_model,
                                         prompt_version=evaluator_prompt_version)
        return {**result, 'correct_count': result['collected_item_count'],
                'total_count': result['total_item_count']}

    def get_status(self, batch_id: str) -> Optional[dict]:
        state = self.batches.get(batch_id)
        if not state:
            return None
        return {
            "batch_id": state["batch_id"],
            "status": state["status"],
            "total": state["total"],
            "completed": state["completed"],
            "failed": state["failed"],
            "running": state["running"],
            "results": [
                {k: v for k, v in r.items()}
                for r in state["results"]
            ],
        }

    def stop_batch(self, batch_id: str) -> bool:
        state = self.batches.get(batch_id)
        if not state:
            return False
        state["cancel_event"].set()
        if state["task"] and not state["task"].done():
            state["task"].cancel()
        state["status"] = "stopping"
        return True
