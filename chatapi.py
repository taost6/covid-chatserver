from fastapi import FastAPI, Body, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from typing import List, Union
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import uuid
import os
import asyncio
import json
from datetime import datetime, timezone, timedelta
from random import random, choice
from hashlib import sha1

from modelChat import *
from modelUserDef import *
from modelHistory import *
from modelRole import PatientRoleProvider
import modelDatabase
from modelSession import Session as SessionModel # New
from openai import NotFoundError
from openai_assistant import OpenAIAssistantWrapper

class APISession(BaseModel):
    users: List[Union[UserDef, AssistantDef]]
    history: History
    session_id: str

# --- Global State ---
users_waiting = {}
users_session = {}

# --- Helper Functions (Top Level) ---
def get_id() -> str:
    base = f"{datetime.now().timestamp()}-{random()}"
    return sha1(base.encode()).hexdigest()

async def log_message(db: Session, session_id: str, user_name: str, patient_id: str, user_role: str, sender: str, message: str, logger, is_initial_message: bool = False):
    if not modelDatabase.SessionLocal:
        return
    try:
        # JST (UTC+9) のタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        # ログメッセージが作成された正確な時刻を記録
        log_entry = modelDatabase.ChatLog(
            session_id=session_id, user_name=user_name, patient_id=patient_id,
            user_role=user_role, sender=sender, message=message,
            is_initial_message=is_initial_message,
            created_at=datetime.now(jst)
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        logger.debug(f"Logged message for session {session_id}")
    except Exception as e:
        logger.error(f"Failed to log message: {e}")
        db.rollback()

async def _mark_session_completed(db: Session, session_id: str, logger):
    try:
        db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id
        ).update({modelDatabase.ChatLog.completed: True})
        db.commit()
        logger.debug(f"Session {session_id} marked as completed.")
    except Exception as e:
        logger.error(f"Failed to mark session as completed: {e}")
        db.rollback()

async def _save_history(session_id: str, history: History, logger) -> None:
    filename = f"history-{session_id}.json"
    with open(filename, "w", encoding="utf-8") as fd:
        json.dump(history.model_dump(exclude={'session_id'}), fd, ensure_ascii=False)
    logger.debug(f"History has been saved {filename}")

def _find_peer_human(user: UserDef) -> UserDef:
    peer_role = "保健師" if user.role == "患者" else "患者"
    for u in users_waiting.values():
        if u.role == peer_role and u.status == Status.Prepared.name:
            return u
    return None

def _find_peer_ai(user: UserDef) -> AssistantDef:
    assistants = json.load(open("assistants.json"))
    if user.role == "保健師":
        return AssistantDef(
            user_id=get_id(), role="患者",
            assistant_id=assistants[0],
        )
    elif user.role == "患者":
        return AssistantDef(
            user_id=get_id(), role="保健師",
            assistant_id=assistants[1],
        )
    return None

def _find_user_session(user_id: str) -> APISession:
    for s in users_session.values():
        for u in s.users:
            if u.user_id == user_id:
                return s
    return None

async def _execute_debriefing(session: APISession, user: UserDef, db: Session, logger, oaw: OpenAIAssistantWrapper):
    """Debriefing処理を実行し、結果をクライアントに送信する"""
    peer_ai = next((p for p in session.users if isinstance(p, AssistantDef)), None)
    
    if not (peer_ai and oaw):
        logger.warning("Debriefing requested but no AI peer or OAW found.")
        return

    # 既存のRunをキャンセルする
    await oaw.cancel_run(peer_ai.thread_id)

    if user.role != "保健師":
        logger.info(f"Debriefing skipped for user role: {user.role}")
        await user.ws.send_json(SessionTerminated(session_id=session.session_id, reason="Session ended by user.").dict())
        await user.ws.close()
        return

    debriefing_tool = {
        "type": "function",
        "function": {
            "name": "submit_debriefing_report",
            "description": "ユーザー（保健師役）の聞き取りスキルに関する評価レポートを提出します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "overall_score": {
                        "type": "integer",
                        "description": "総合評価（100点満点）"
                    },
                    "information_retrieval_ratio": {
                        "type": "string",
                        "description": "感染経路の特定や濃厚接触者の把握に繋がる重要な情報を、これまでの会話からどの程度の割合で聴取できたかの評価。"
                    },
                    "information_quality": {
                        "type": "string",
                        "description": "患者役が回答した情報の質。どれだけ効率的に有益な情報を引き出せたかの指標。"
                    },
                    "micro_evaluations": {
                        "type": "array",
                        "description": "ユーザーの個々の発言に対するミクロな評価のリスト。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "utterance": {"type": "string", "description": "評価対象のユーザーの発言"},
                                "evaluation_symbol": {"type": "string", "enum": ["◎", "○", "△", "✕"], "description": "記号による評価"},
                                "advice": {"type": "string", "description": "具体的なアドバイス"}
                            },
                            "required": ["utterance", "evaluation_symbol", "advice"]
                        }
                    },
                    "overall_comment": {
                        "type": "string",
                        "description": "全体的な総評。"
                    }
                },
                "required": ["overall_score", "information_retrieval_ratio", "information_quality", "micro_evaluations", "overall_comment"]
            }
        }
    }

    # 対話履歴をプロンプト用に整形
    conversation_history = "\n".join([f"{msg.role}: {msg.text}" for msg in session.history.history if msg.role in ["保健師", "患者"]])
    debriefing_prompt = (
        "あなたは、これまでのユーザー（保健師役）との対話を評価する専門家です。"
        "以下の対話履歴を分析し、`submit_debriefing_report`関数を呼び出して、聞き取りスキルを評価してください。\n\n"
        f"【対話履歴】\n{conversation_history}\n\n"
        "評価の際は、感染経路の特定や濃厚接触者の把握に繋がる重要な情報（いつ・どこで・誰と）が、"
        "どの程度引き出せているかを厳密に評価してください。"
        "良かったポイントは積極的に評価し、改善につながるポジティブなフィードバックをお願いします。"
    )

    _, tool_call = await oaw.send_message(
        peer_ai,
        debriefing_prompt,
        tools=[debriefing_tool],
        tool_choice={"type": "function", "function": {"name": "submit_debriefing_report"}}
    )

    debriefing_data = None
    if tool_call and tool_call.function.name == "submit_debriefing_report":
        try:
            args = json.loads(tool_call.function.arguments)
            debriefing_data = args
            logger.info("Successfully parsed debriefing report from function calling.")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse debriefing tool call arguments: {e}")
            logger.error(f"Raw arguments: {tool_call.function.arguments}")
            debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 評価データの解析エラー）"}
    else:
        logger.error(f"Debriefing failed. Expected tool call 'submit_debriefing_report' but got: {tool_call}")
        debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: AIが評価データを生成できませんでした）"}

    await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_data=debriefing_data).dict())
    # ログにはJSON全体を保存する
    await log_message(db, session.session_id, "System", peer_ai.assistant_id, peer_ai.role, "System", f"Debriefing Data: {json.dumps(debriefing_data, ensure_ascii=False)}", logger)


# --- Main API Factory ---
def api(config):
    logger = config.logger
    oaw = OpenAIAssistantWrapper(config)
    role_provider = PatientRoleProvider(config)
    
    app = FastAPI()

    @app.on_event("startup")
    async def startup_event():
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            logger.info("Initializing Database...")
            modelDatabase.initialize_database(db_url)
            modelDatabase.init_db()
            logger.info("Database initialized.")
        else:
            logger.warning("DATABASE_URL is not set. Running without database logging.")
        
        logger.info("Initializing PatientRoleProvider...")
        try:
            await role_provider.initialize()
            logger.info("PatientRoleProvider initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize PatientRoleProvider: {e}")

    def get_db():
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
        db = modelDatabase.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # --- API Endpoints ---
    @app.get("/v1/patients")
    async def get_available_patients():
        if role_provider.df is None:
            raise HTTPException(status_code=503, detail="Patient data is not ready.")
        return {"patient_ids": role_provider.get_available_patient_ids()}

    @app.get("/v1/patient/{patient_id}")
    async def get_patient_details(patient_id: str):
        if role_provider.df is None:
            raise HTTPException(status_code=503, detail="Patient data is not ready.")
        details = role_provider.get_patient_details(patient_id)
        if "error" in details:
            raise HTTPException(status_code=404, detail=details['error'])
        return details

    @app.get("/v1/session/{session_id}")
    async def get_session_status(session_id: str, db: Session = Depends(get_db)):
        """指定されたセッションが再開可能か確認し、関連情報を返す"""
        logger.info(f"Attempting to restore session with session_id: {session_id}") # DEBUG LOG
        # Query the new sessions table
        db_session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id,
            SessionModel.status == 'active'
        ).first()

        if not db_session:
            raise HTTPException(status_code=404, detail="Active session not found.")

        # If session is found, proceed to gather history and other details
        if role_provider.df is None:
            logger.warning("Role provider not initialized in get_session_status. Initializing...")
            await role_provider.initialize()
            if role_provider.df is None:
                raise HTTPException(status_code=503, detail="Patient data could not be loaded on demand.")

        history_logs = db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id,
            modelDatabase.ChatLog.sender != 'System',  # システムログは除外
            modelDatabase.ChatLog.is_initial_message == False # 初期メッセージは除外
        ).order_by(modelDatabase.ChatLog.created_at.asc()).all()

        chat_history = []
        user_icon = 'mdi-account-tie-woman' if db_session.user_role == '保健師' else 'mdi-account'
        assistant_icon = 'mdi-account' if db_session.user_role == '保健師' else 'mdi-account-tie-woman'

        for log in history_logs:
            if log.sender == 'User':
                chat_history.append({
                    "sender": "user",
                    "message": log.message,
                    "icon": user_icon
                })
            elif log.sender == 'Assistant':
                chat_history.append({
                    "sender": "assistant",
                    "message": log.message,
                    "icon": assistant_icon
                })

        patient_info = {}
        if db_session.user_role == '保健師' and db_session.patient_id:
            patient_info = role_provider.get_patient_details(db_session.patient_id)

        # Create a new user_id for the restored session to allow reconnection
        new_user_id = get_id()
        restored_user = UserDef(
            user_id=new_user_id,
            user_name=db_session.user_name,
            role=db_session.user_role,
            status=Status.Registered.name, # Set as Registered to allow WS connection
            target_patient_id=db_session.patient_id,
            session_id=session_id # Pass the session_id for reconnection
        )
        users_waiting[new_user_id] = restored_user

        return {
            "session_id": session_id,
            "user_id": new_user_id, # Return the NEW user_id
            "user_name": db_session.user_name,
            "user_role": db_session.user_role,
            "patient_id": db_session.patient_id,
            "chat_history": chat_history,
            "patient_info": patient_info,
            "interview_date": db_session.interview_date or db_session.created_at.strftime("%Y年%m月%d日"),
        }

    @app.get("/v1/logs")
    async def get_logs(db: Session = Depends(get_db)):
        """対話ログのセッション一覧を取得する"""
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")

        sessions = db.query(SessionModel).order_by(
            desc(SessionModel.created_at)
        ).all()
        
        return [
            {
                "session_id": session.session_id,
                "user_name": session.user_name,
                "user_role": session.user_role,
                "patient_id": session.patient_id,
                "started_at": session.created_at.isoformat()
            } for session in sessions
        ]

    @app.get("/v1/logs/{session_id}")
    async def get_log_detail(session_id: str, db: Session = Depends(get_db)):
        """特定のセッションの対話ログ詳細を取得する"""
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
            
        logs = db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id
        ).order_by(
            modelDatabase.ChatLog.created_at
        ).all()
        
        if not logs:
            raise HTTPException(status_code=404, detail="Session not found")
            
        return [
            {
                "id": log.id,
                "sender": log.sender,
                "role": log.user_role,
                "message": log.message,
                "created_at": log.created_at.isoformat()
            } for log in logs
        ]

    @app.post("/v1")
    async def post_request(req: RegistrationRequest, db: Session = Depends(get_db)):
        if req.msg_type != MsgType.RegistrationRequest.name:
            raise HTTPException(status_code=406, detail="Invalid message type")
        
        user_id = get_id()
        session_id = str(uuid.uuid4())
        users_waiting[user_id] = UserDef(
            user_id=user_id, user_name=req.user_name, role=req.user_role,
            status=Status.Registered.name, target_patient_id=req.target_patient_id,
            session_id=session_id
        )
        return RegistrationAccepted(user_id=user_id, session_id=session_id)

    @app.websocket("/v1/ws/{user_id}")
    async def websocket_endpoint(user_id: str, ws: WebSocket, db: Session = Depends(get_db)):
        if user_id not in users_waiting:
            await ws.close(code=1008)
            return

        await ws.accept()
        user = users_waiting[user_id]
        user.ws = ws
        user.status = Status.Prepared.name

        try:
            # Case 1: Reconnecting to a session active in memory
            active_session = users_session.get(user.session_id)
            if active_session:
                logger.info(f"Reconnecting user {user.user_id} to active session {user.session_id}")
                # Update WebSocket object
                for i, u in enumerate(active_session.users):
                    if isinstance(u, UserDef):
                        active_session.users[i].ws = ws
                        break
                # History is already in memory, so just start the handler
                await _session_handler(user, db, logger, oaw)
                return

            # Case 2: Restoring a session from DB (e.g., after server restart)
            db_session = db.query(SessionModel).filter(SessionModel.session_id == user.session_id).first()
            if db_session and db_session.status == 'active':
                logger.info(f"No active session in memory for {user.session_id}. Rebuilding from DB.")
                assistant = _find_peer_ai(user)
                assistant.thread_id = db_session.thread_id
                history = History(assistant={"role": assistant.role, "assistant_id": assistant.assistant_id})
                active_session = APISession(users=[user, assistant], history=history, session_id=user.session_id)
                users_session[user.session_id] = active_session

                # Restore history from DB
                history_logs = db.query(modelDatabase.ChatLog).filter(
                    modelDatabase.ChatLog.session_id == active_session.session_id,
                    modelDatabase.ChatLog.sender != 'System'
                ).order_by(modelDatabase.ChatLog.created_at.asc()).all()

                for log in history_logs:
                    user_role = user.role
                    assistant_role = "患者" if user_role == "保健師" else "保健師"
                    role = user_role if log.sender == 'User' else assistant_role
                    active_session.history.history.append(MessageInfo(role=role, text=log.message))
                
                logger.info(f"Restored {len(history_logs)} messages to server-side session history for session {user.session_id}.")
                await _session_handler(user, db, logger, oaw)
                return

            # Case 3: Creating a new session
            logger.info(f"Creating a new session for user {user.user_id}")
            peer = _find_peer_human(user)
            if peer:
                session_id = user.session_id or get_id() # Fallback for safety
                session = APISession(users=[user, peer], history=History(), session_id=session_id)
                users_session[session_id] = session
                del users_waiting[user.user_id]
                del users_waiting[peer.user_id]
                
                await peer.ws.send_json(Established(session_id=session_id).dict())
                await user.ws.send_json(Established(session_id=session_id).dict())
                await _session_handler(user, db, logger)
            else:
                assistant = _find_peer_ai(user)
                if assistant:
                    session_id = user.session_id
                    if not session_id:
                        logger.error(f"Session ID is missing for user {user.user_id}. Cannot establish session.")
                        await user.ws.close(code=1011, reason="Internal server error: session_id missing")
                        return

                    # Check if session already exists in the database
                    db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()

                    if not db_session:
                        # Create a new session record in the database only if it doesn't exist
                        logger.info(f"Creating session record for session_id: {session_id}")
                        db_session = SessionModel(
                            session_id=session_id,
                            user_name=user.user_name,
                            user_role=user.role,
                            patient_id=user.target_patient_id if user.role == "保健師" else None,
                            status='active'
                        )
                        db.add(db_session)
                        db.commit()
                        db.refresh(db_session)

                    # Reuse or create thread_id and interview_date
                    interview_date_str = db_session.interview_date
                    if db_session.thread_id:
                        assistant.thread_id = db_session.thread_id
                        logger.info(f"Reusing existing thread_id: {assistant.thread_id}")
                        prompt_needed = False
                    else:
                        assistant.thread_id = await oaw.create_thread()
                        db_session.thread_id = assistant.thread_id
                        # interview_date is set below, so commit together
                        prompt_needed = True

                    history = History(assistant={"role": assistant.role, "assistant_id": assistant.assistant_id})
                    session = APISession(users=[user, assistant], history=history, session_id=session_id)
                    users_session[session_id] = session
                    del users_waiting[user.user_id]

                    if assistant.role == "患者":
                        patient_id_for_ai = user.target_patient_id or "1"
                        
                        if prompt_needed:
                            prompt_chunks, interview_date_str = role_provider.get_patient_prompt_chunks(patient_id_for_ai)
                            db_session.interview_date = interview_date_str
                            db.commit()
                            logger.info(f"Saved new interview_date: {interview_date_str}")
                        else:
                            prompt_chunks, _ = role_provider.get_patient_prompt_chunks(patient_id_for_ai, interview_date_str=db_session.interview_date)

                        if prompt_needed and interview_date_str:
                            for chunk in prompt_chunks:
                                await oaw.add_message_to_thread(assistant.thread_id, chunk)
                                history.history.append(MessageInfo(role="system", text=chunk))
                                await log_message(db, session_id, user.user_name, patient_id_for_ai, user.role, "System", chunk, logger)
                            
                            patient_details = role_provider.get_patient_details(patient_id_for_ai)
                            patient_name = patient_details.get("name", "名無し")
                            initial_bot_message = f"私の名前は{patient_name}です。何でも聞いてください。"
                            history.history.append(MessageInfo(role="患者", text=initial_bot_message))
                            await log_message(db, session_id, "AI", patient_id_for_ai, "患者", "Assistant", initial_bot_message, logger, is_initial_message=True)
                        elif prompt_needed:
                             logger.error(f"Failed to generate prompt for patient ID {patient_id_for_ai}")

                    elif assistant.role == "保健師":
                        if prompt_needed:
                            interview_date_str = datetime.now().strftime("%Y年%m月%d日")
                            db_session.interview_date = interview_date_str
                            db.commit()

                            prompt_chunks, initial_bot_message = role_provider.get_interviewer_prompt_chunks()
                            for chunk in prompt_chunks:
                                await oaw.add_message_to_thread(assistant.thread_id, chunk)
                                history.history.append(MessageInfo(role="system", text=chunk))
                                await log_message(db, session_id, user.user_name, "N/A", user.role, "System", chunk, logger)
                            
                            history.history.append(MessageInfo(role="保健師", text=initial_bot_message))
                            await log_message(db, session_id, "AI", assistant.assistant_id, "保健師", "Assistant", initial_bot_message, logger, is_initial_message=True)
                            await user.ws.send_json(MessageForwarded(session_id=session_id, user_msg=initial_bot_message).dict())

                    final_interview_date = db_session.interview_date or db_session.created_at.strftime("%Y年%m月%d日")
                    await user.ws.send_json(Established(session_id=session_id, interview_date=final_interview_date).dict())
                    await _session_handler(user, db, logger, oaw)
                else:
                    await user.ws.send_json(Prepared().dict())
                    await _session_handler(user, db, logger)
        except WebSocketDisconnect:
            logger.debug(f"WS Exception: {user.user_id}")
        finally:
            if user_id in users_waiting: del users_waiting[user_id]
            session = _find_user_session(user_id)
            if session:
                for u in session.users:
                    if u.user_id != user_id and hasattr(u, 'ws') and u.ws:
                        await u.ws.close(code=1001)
                del users_session[session.session_id]

    async def _session_handler(user: UserDef, db: Session, logger, oaw: OpenAIAssistantWrapper = None):
        session = _find_user_session(user.user_id)
        if not session: return

        try:
            while True:
                data = await user.ws.receive_json()
                msg_type = data.get("msg_type")

                if msg_type == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    await log_message(db, session.session_id, user.user_name, user.target_patient_id, user.role, "User", m.user_msg, logger, is_initial_message=False)
                    session.history.history.append(MessageInfo(role=user.role, text=m.user_msg))

                    for peer in session.users:
                        if peer.user_id == user.user_id: continue
                        
                        if isinstance(peer, AssistantDef) and oaw:
                            try:
                                response_msg, tool_call = await oaw.send_message(peer, m.user_msg)
                            except NotFoundError:
                                logger.warning(f"Thread {peer.thread_id} not found. Recreating thread...")
                                # スレッドを再作成し、DBとセッション情報を更新
                                new_thread_id = await oaw.create_thread()
                                peer.thread_id = new_thread_id
                                db_session = db.query(SessionModel).filter(SessionModel.session_id == session.session_id).first()
                                if db_session:
                                    db_session.thread_id = new_thread_id
                                    db.commit()
                                
                                # プロンプトを再注入する必要がある
                                if peer.role == "患者":
                                    patient_id_for_ai = user.target_patient_id or "1"
                                    prompt_chunks, _ = role_provider.get_patient_prompt_chunks(patient_id_for_ai, interview_date_str=db_session.interview_date if db_session else None)
                                    for chunk in prompt_chunks:
                                        await oaw.add_message_to_thread(peer.thread_id, chunk)
                                elif peer.role == "保健師":
                                    prompt_chunks, _ = role_provider.get_interviewer_prompt_chunks()
                                    for chunk in prompt_chunks:
                                        await oaw.add_message_to_thread(peer.thread_id, chunk)

                                logger.info(f"Re-sending message to new thread {new_thread_id}")
                                response_msg, tool_call = await oaw.send_message(peer, m.user_msg)

                            if tool_call and tool_call.function.name == "end_conversation_and_start_debriefing":
                                # LLMが会話の終了を判断した場合、クライアントに通知して確認を促す
                                logger.info(f"Tool call detected: {tool_call.function.name}. Notifying client...")
                                await user.ws.send_json(ToolCallDetected(session_id=session.session_id).dict())
                            elif response_msg:
                                if response_msg.startswith("FAILED:"):
                                    # エラー応答
                                    logger.error(f"AI response failed: {response_msg}")
                                    await user.ws.send_json(MessageRejected(session_id=session.session_id, reason=response_msg).dict())
                                else:
                                    # 通常のテキスト応答
                                    session.history.history.append(MessageInfo(role=peer.role, text=response_msg))
                                    await log_message(db, session.session_id, "AI", peer.assistant_id, peer.role, "Assistant", response_msg, logger, is_initial_message=False)
                                    await user.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=response_msg).dict())
                        elif isinstance(peer, UserDef):
                            await log_message(db, session.session_id, peer.user_name, peer.target_patient_id, peer.role, "Assistant", m.user_msg, logger, is_initial_message=False)
                            await peer.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=m.user_msg).dict())

                elif msg_type == MsgType.DebriefingRequest.name:
                    m = DebriefingRequest.model_validate(data)
                    logger.info(f"DebriefingRequest received from user: {m.user_id}")
                    await _execute_debriefing(session, user, db, logger, oaw)

                elif msg_type == MsgType.EndSessionRequest.name:
                    m = EndSessionRequest.model_validate(data)
                    await _save_history(session.session_id, session.history, logger)
                    
                    # Mark session as completed in the new table
                    db_session = db.query(SessionModel).filter(SessionModel.session_id == session.session_id).first()
                    if db_session:
                        db_session.status = 'completed'
                        db_session.completed_at = datetime.now()
                        db.commit()

                    for u in session.users:
                        if hasattr(u, 'ws') and u.ws:
                            reason = "EndSession request is accepted." if u.user_id == m.user_id else "Peer sent the end of session."
                            await u.ws.send_json(SessionTerminated(session_id=session.session_id, reason=reason).dict())
                            await u.ws.close()
                        if isinstance(u, AssistantDef) and oaw:
                            await oaw.delete_thread(u)
                    break
        except WebSocketDisconnect:
            logger.debug(f"WS Disconnect in session: {user.user_id}")
        except Exception as e:
            logger.error(f"Error in session handler: {e}")
        finally:
            if session.session_id in users_session:
                del users_session[session.session_id]

    app.mount("/", StaticFiles(directory=config.www_path, html=True), name="www")
    return app
