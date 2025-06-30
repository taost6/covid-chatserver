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
            # Check if this user is reconnecting to an existing session
            active_session = None
            for s in users_session.values():
                for u in s.users:
                    if isinstance(u, UserDef) and u.user_name == user.user_name and u.role == user.role:
                        # A simple check, might need to be more robust
                        active_session = s
                        break
                if active_session:
                    break

            if active_session:
                # This is a reconnection, update the websocket object
                for i, u in enumerate(active_session.users):
                    if isinstance(u, UserDef) and u.user_name == user.user_name:
                        active_session.users[i].ws = ws
                        break
                # No need to send Established again, client already has the history
                await _session_handler(user, db, logger, oaw)
                return

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
                            response_msg = await oaw.send_message(peer, m.user_msg)
                            session.history.history.append(MessageInfo(role=peer.role, text=response_msg))
                            await log_message(db, session.session_id, "AI", peer.assistant_id, peer.role, "Assistant", response_msg, logger, is_initial_message=False)
                            await user.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=response_msg).dict())
                        elif isinstance(peer, UserDef):
                            await log_message(db, session.session_id, peer.user_name, peer.target_patient_id, peer.role, "Assistant", m.user_msg, logger, is_initial_message=False)
                            await peer.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=m.user_msg).dict())

                elif msg_type == MsgType.DebriefingRequest.name:
                    m = DebriefingRequest.model_validate(data)
                    
                    peer_ai = next((p for p in session.users if isinstance(p, AssistantDef)), None)
                    
                    if peer_ai and oaw:
                        debriefing_prompt = (
                            "あなたは、これまでのユーザー（保健師役）との対話を評価する専門家です。"
                            "以下の要件に従って、保健師役のユーザーの聞き取りスキルを評価し、フィードバックを生成してください。\n\n"
                            "評価の要件：\n"
                            "1. 総合評価を100点満点で採点し、最初に「総合得点：○○点」として示してください。（100点満点）\n"
                            "2. 感染経路の特定や濃厚接触者の把握に繋がる重要な情報を、これまでの会話からどの程度の割合で聴取できたかを評価してください。\n"
                            "3. ユーザーが引き出した情報の量を評価してください。\n"
                            "4. ユーザーの個々の発言について、ミクロな評価を行ってください。評価は「どの発言に対してか（ここは実際の値に置き換える）：記号による評価（◎、○、△、✕）：ユーザーの発言への具体的なアドバイス」の形式で、複数並べてください。\n\n"
                            "以上の要件をすべて満たした評価レポートを生成してください。"
                        )
                        
                        debriefing_text = await oaw.send_message(peer_ai, debriefing_prompt)
                        
                        await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_text=debriefing_text).dict())
                        
                        await log_message(db, session.session_id, "System", peer_ai.assistant_id, peer_ai.role, "System", f"Debriefing: {debriefing_text}", logger)

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
