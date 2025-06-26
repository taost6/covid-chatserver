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
from datetime import datetime
from random import random, choice
from hashlib import sha1

from modelChat import *
from modelUserDef import *
from modelHistory import *
from modelRole import PatientRoleProvider
import modelDatabase
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

async def log_message(db: Session, session_id: str, user_name: str, patient_id: str, user_role: str, sender: str, message: str, logger):
    if not modelDatabase.SessionLocal:
        return
    try:
        log_entry = modelDatabase.ChatLog(
            session_id=session_id, user_name=user_name, patient_id=patient_id,
            user_role=user_role, sender=sender, message=message
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        logger.debug(f"Logged message for session {session_id}")
    except Exception as e:
        logger.error(f"Failed to log message: {e}")
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
    if user.role != "保健師":
        return None
    return AssistantDef(
        user_id=get_id(), role="患者",
        assistant_id=choice(json.load(open("assistants.json"))),
    )

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

    @app.get("/v1/logs")
    async def get_logs(db: Session = Depends(get_db)):
        """対話ログのセッション一覧を取得する"""
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
        
        # サブクエリで各セッションの最初のログIDを取得
        subquery = db.query(
            modelDatabase.ChatLog.session_id,
            func.min(modelDatabase.ChatLog.id).label('min_id')
        ).filter(
            modelDatabase.ChatLog.user_role == '保健師',
            modelDatabase.ChatLog.user_name != 'AI'
        ).group_by(modelDatabase.ChatLog.session_id).subquery()

        # サブクエリの結果を使って、実際のログエントリを取得
        sessions = db.query(modelDatabase.ChatLog).join(
            subquery,
            modelDatabase.ChatLog.id == subquery.c.min_id
        ).order_by(
            desc(modelDatabase.ChatLog.created_at)
        ).all()
        
        return [
            {
                "session_id": session.session_id,
                "user_name": session.user_name,
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
            status=Status.Registered.name, target_patient_id=req.target_patient_id
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
            peer = _find_peer_human(user)
            if peer:
                session_id = get_id()
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
                    session_id = get_id()
                    assistant.thread_id = await oaw.create_thread()
                    history = History(assistant={"role": "患者", "assistant_id": assistant.assistant_id})
                    session = APISession(users=[user, assistant], history=history, session_id=session_id)
                    users_session[session_id] = session
                    del users_waiting[user.user_id]

                    patient_id_for_ai = user.target_patient_id or "1"
                    prompt_chunks, interview_date_str = role_provider.get_patient_prompt_chunks(patient_id_for_ai)
                    
                    if interview_date_str:
                        for chunk in prompt_chunks:
                            await oaw.add_message_to_thread(assistant.thread_id, chunk)
                            history.history.append(MessageInfo(role="system", text=chunk))
                            await log_message(db, session_id, user.user_name, patient_id_for_ai, user.role, "System", chunk, logger)
                        
                        initial_bot_message = "何でも聞いてください"
                        history.history.append(MessageInfo(role="患者", text=initial_bot_message))
                        await log_message(db, session_id, "AI", patient_id_for_ai, "患者", "Assistant", initial_bot_message, logger)
                        await user.ws.send_json(MessageForwarded(session_id=session_id, user_msg=initial_bot_message).dict())
                    else:
                        logger.error(f"Failed to generate prompt for patient ID {patient_id_for_ai}")
                        interview_date_str = datetime.now().strftime("%Y年%m月%d日")

                    await user.ws.send_json(Established(session_id=session_id, interview_date=interview_date_str).dict())
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
                    await log_message(db, session.session_id, user.user_name, user.target_patient_id, user.role, "User", m.user_msg, logger)
                    session.history.history.append(MessageInfo(role=user.role, text=m.user_msg))

                    for peer in session.users:
                        if peer.user_id == user.user_id: continue
                        
                        if isinstance(peer, AssistantDef) and oaw:
                            response_msg = await oaw.send_message(peer, m.user_msg)
                            session.history.history.append(MessageInfo(role=peer.role, text=response_msg))
                            await log_message(db, session.session_id, "AI", peer.assistant_id, peer.role, "Assistant", response_msg, logger)
                            await user.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=response_msg).dict())
                        elif isinstance(peer, UserDef):
                            await log_message(db, session.session_id, peer.user_name, peer.target_patient_id, peer.role, "Assistant", m.user_msg, logger)
                            await peer.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=m.user_msg).dict())

                elif msg_type == MsgType.EndSessionRequest.name:
                    m = EndSessionRequest.model_validate(data)
                    await _save_history(session.session_id, session.history, logger)
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
