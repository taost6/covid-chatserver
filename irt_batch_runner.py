"""
IRT バッチ実行エンジン
ヘッドレス（WebSocket不要）でAI対話を実行し、完了後にIRT正誤判定を行う。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from modelUserDef import AssistantDef
from modelRole import PatientRoleProvider
from modelSession import Session as SessionModel
from modelPrompt import PromptTemplateService
from modelIRT import IRTPatientInstanceService, IRTResponseJudgmentService
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
                    logger.warning(f"[Batch] Session {session_id}: AI response failed: {response_msg}")
                    break

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

    async def start_batch(self, patient_ids: List[str], runs_per_patient: int, concurrency: int,
                          nurse_model: Optional[str] = None, patient_model: Optional[str] = None,
                          evaluator_model: Optional[str] = None,
                          patient_prompt_version: Optional[int] = None,
                          interviewer_prompt_version: Optional[int] = None,
                          evaluator_prompt_version: Optional[int] = None) -> str:
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
        return batch_id

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
                    "correct_count": None,
                    "total_count": None,
                    "error": None,
                }
                state["results"].append(result_entry)
                state["running"] += 1

                db = None
                try:
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
                    prompt_db.close()

                    db_session = SessionModel(
                        session_id=session_id,
                        user_name="IRT_Batch",
                        user_role="傍聴者",
                        patient_id=patient_id,
                        status='active',
                        patient_version=patient_tmpl.version if patient_tmpl else None,
                        interviewer_version=interviewer_tmpl.version if interviewer_tmpl else None,
                        patient_model=state["patient_model"],
                        interviewer_model=state["nurse_model"],
                        evaluator_model=state["evaluator_model"],
                    )
                    db.add(db_session)
                    db.commit()

                    # ヘッドレス対話実行
                    conv = HeadlessConversation(
                        self.oaw, self.role_provider, db,
                        nurse_model=state["nurse_model"],
                        patient_model=state["patient_model"],
                        patient_prompt_version=p_ver,
                        interviewer_prompt_version=i_ver,
                    )
                    conv_result = await conv.run(patient_id, session_id)

                    # セッション完了
                    db_session.status = 'completed'
                    db_session.completed_at = datetime.now(JST)
                    if conv_result.get("interview_date"):
                        db_session.interview_date = conv_result["interview_date"]
                    db.commit()

                    # IRT判定実行
                    judgment_result = await self._execute_irt_judgment_for_batch(
                        session_id, db, evaluator_model=state["evaluator_model"],
                        evaluator_prompt_version=state.get("evaluator_prompt_version")
                    )

                    result_entry["status"] = "completed"
                    result_entry["correct_count"] = judgment_result.get("correct_count", 0)
                    result_entry["total_count"] = judgment_result.get("total_count", 0)
                    state["completed"] += 1

                    logger.info(
                        f"[Batch {batch_id}] patient={patient_id} run={run_number} "
                        f"session={session_id} turns={conv_result['turn_count']} "
                        f"ended_by={conv_result['ended_by']} "
                        f"correct={result_entry['correct_count']}/{result_entry['total_count']}"
                    )

                except Exception as e:
                    logger.error(f"[Batch {batch_id}] Failed: patient={patient_id} run={run_number}: {e}")
                    result_entry["status"] = "failed"
                    result_entry["error"] = str(e)
                    state["failed"] += 1
                    if db:
                        db.rollback()
                finally:
                    state["running"] -= 1
                    if db:
                        db.close()

        # タスクリスト生成
        tasks = []
        for pid in patient_ids:
            for run_num in range(1, runs_per_patient + 1):
                tasks.append(run_one(pid, run_num))

        await asyncio.gather(*tasks, return_exceptions=True)

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
        """バッチ用IRT判定（chatapi._execute_irt_judgmentのロジックを再利用）"""

        session_record = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not session_record:
            raise RuntimeError(f"Session {session_id} not found")

        patient_id = session_record.patient_id
        if not patient_id:
            raise RuntimeError(f"Session {session_id} has no patient_id")

        # 対話ログ取得
        chat_logs = db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id,
            modelDatabase.ChatLog.sender.in_(["User", "Assistant"]),
            modelDatabase.ChatLog.is_initial_message == False
        ).order_by(modelDatabase.ChatLog.created_at).all()

        if not chat_logs:
            raise RuntimeError(f"No chat logs found for session {session_id}")

        conversation_history = "\n".join([
            f"{log.ai_role or log.user_role}: {log.message}"
            for log in chat_logs
            if log.message and not log.message.startswith("Debriefing Data:")
        ])

        # IRTインスタンス取得
        instance_service = IRTPatientInstanceService(db)
        instances = instance_service.get_instances_for_patient(patient_id)
        if not instances:
            raise RuntimeError(f"No IRT instances found for patient {patient_id}")

        detectable_instances = [inst for inst in instances if inst.is_detectable]
        if not detectable_instances:
            raise RuntimeError(f"No detectable IRT instances for patient {patient_id}")

        instances_text = "\n".join([
            f"- ID:{inst.id} [{inst.item_type_code}] {inst.description or ''}"
            for inst in detectable_instances
        ])

        # 判定用プロンプト取得
        prompt_db = modelDatabase.PromptSessionLocal()
        try:
            prompt_service = PromptTemplateService(prompt_db)
            if evaluator_prompt_version is not None:
                irt_eval_template = prompt_service.get_template_by_version('evaluator', evaluator_prompt_version)
            else:
                irt_eval_template = prompt_service.get_active_template('evaluator')
        finally:
            prompt_db.close()

        if not irt_eval_template:
            raise RuntimeError("評価者プロンプトがDBに登録されていません。プロンプト管理画面から登録してください。")

        base_prompt = irt_eval_template.prompt_text

        full_prompt = (
            f"{base_prompt}\n\n"
            f"【判定対象のIRT項目一覧】\n{instances_text}\n\n"
            f"【対話履歴】\n{conversation_history}\n\n"
            f"上記の対話履歴を分析し、各IRT項目について submit_irt_judgments 関数を呼び出して判定結果を提出してください。"
        )

        irt_judgment_tool = {
            "type": "function",
            "name": "submit_irt_judgments",
            "description": "対話ログに基づき、各IRT項目が正しく聴取されたかの判定結果を提出する",
            "parameters": {
                "type": "object",
                "properties": {
                    "judgments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "instance_id": {"type": "integer", "description": "IRT項目インスタンスのID"},
                                "is_correct": {"type": "boolean", "description": "正しく聴取されたか"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "確信度"},
                                "reasoning": {"type": "string", "description": "判定の根拠"}
                            },
                            "required": ["instance_id", "is_correct", "confidence", "reasoning"]
                        }
                    }
                },
                "required": ["judgments"]
            }
        }

        # LLM呼び出し
        with open("assistants.json", "r") as f:
            assistants = json.load(f)
        if len(assistants) < 3:
            raise RuntimeError("Evaluator assistant ID not found in assistants.json")

        judgment_thread_id = None
        try:
            judgment_thread_id = await self.oaw.create_thread()

            judgment_assistant = AssistantDef(
                user_id=get_id(), role="評価者",
                assistant_id=assistants[2], thread_id=judgment_thread_id
            )

            prompt_chunks = self.role_provider._split_text_for_prompt(full_prompt, 2000)
            for chunk in prompt_chunks:
                await self.oaw.add_message_to_thread(judgment_assistant.thread_id, chunk)

            final_instruction = "上記の情報を分析し、submit_irt_judgments 関数を呼び出して全IRT項目の判定結果を提出してください。"
            response_text, tool_call = await self.oaw.send_message(
                judgment_assistant, final_instruction,
                tools=[irt_judgment_tool],
                tool_choice="required",
                max_retries=5,
                model=evaluator_model
            )

            if not tool_call or tool_call.name != "submit_irt_judgments":
                raise RuntimeError("LLM did not return expected tool call for IRT judgment")

            result = json.loads(tool_call.arguments)
            llm_judgments = result.get("judgments", [])
        finally:
            if judgment_thread_id:
                try:
                    await self.oaw.delete_thread_by_id(judgment_thread_id)
                except Exception:
                    pass

        # 既存判定削除 → 新規保存
        judgment_service = IRTResponseJudgmentService(db)
        judgment_service.delete_judgments_for_session(session_id)

        valid_instance_ids = {inst.id for inst in detectable_instances}
        db_judgments = []
        for j in llm_judgments:
            if j.get("instance_id") not in valid_instance_ids:
                continue
            db_judgments.append({
                "session_id": session_id,
                "instance_id": j["instance_id"],
                "is_correct": j["is_correct"],
                "judgment_method": "ai",
                "confidence": j.get("confidence"),
                "notes": j.get("reasoning"),
            })

        saved = judgment_service.bulk_create_judgments(db_judgments)
        correct_count = sum(1 for j in saved if j.is_correct)

        return {
            "correct_count": correct_count,
            "total_count": len(saved),
        }

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
