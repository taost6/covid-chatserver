from fastapi import FastAPI, Body, Request, HTTPException, Depends
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import status as httpcode
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
import uuid
from modelChat import *
from modelUserDef import *
from modelHistory import *
from modelRole import PatientRoleProvider
from modelDatabase import SessionLocal, ChatLog, init_db
import aiofiles
import json
import dateutil.parser
import asyncio
from openai_assistant import OpenAIAssistantWrapper
from uuid import uuid4
from datetime import datetime
from random import random, choice
from hashlib import sha1

class Session(BaseModel):
    users: List[Union[UserDef,AssistantDef]]
    history: History
    session_id: str

def api(config):

    logger = config.logger

    config.queue = asyncio.Queue(maxsize=config.max_queue_size)
    config.queue._loop = config.loop
    # create OpenAI API wrapper
    oaw = OpenAIAssistantWrapper(config)
    # 
    config.assistant_list = json.load(open(config.assistants_storage,
                                           encoding="utf-8"))

    role_provider = PatientRoleProvider(config)

    app = FastAPI()

    @app.on_event("startup")
    async def startup_event():
        """サーバー起動時にDBとPatientRoleProviderを初期化する"""
        logger.info("Initializing Database...")
        init_db()
        logger.info("Database initialized.")
        
        logger.info("Initializing PatientRoleProvider...")
        try:
            await role_provider.initialize()
            logger.info("PatientRoleProvider initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize PatientRoleProvider: {e}")

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        content = jsonable_encoder(exc.errors())
        logger.error(f"Model Validation Error: {content}")
        return JSONResponse(
            status_code=httpcode.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": content},
        )

    """
    waiting = { <user_id>: UserDef, ... }
    session = {
        <session_id>: {
            users: [UserDef, UserDef|AssistantDef],
            history: [MessageInfo, ...],
        }, ...
    }
    """
    users_waiting = {}
    users_session = {}

    def get_id() -> str:
        """
        user_id
        session_id
        """
        base = f"{datetime.now().timestamp()}-{random()}"
        return sha1(base.encode()).hexdigest()

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    async def log_message(db: Session, session_id: str, user_name: str, patient_id: str, user_role: str, sender: str, message: str):
        try:
            log_entry = ChatLog(
                session_id=session_id,
                user_name=user_name,
                patient_id=patient_id,
                user_role=user_role,
                sender=sender,
                message=message
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            logger.debug(f"Logged message for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to log message: {e}")
            db.rollback()

    async def _save_history(session_id: str, history: History) -> None:
        filename = f"history-{session_id}.json"
        async with aiofiles.open(filename, "w", encoding="utf-8") as fd:
            await fd.write(json.dumps(history.model_dump(exclude={'session_id'}), ensure_ascii=False))
        logger.debug(f"History has been saved {filename}")

    def _find_peer_human(user: UserDef) -> UserDef:
        # find a peer
        if user.role == "患者":
            peer_role = "保健師"
        elif user.role == "保健師":
            peer_role = "患者"
        else:
            logger.error(f"ERROR: invalid user role {user.role}")
            return None

        for u in users_waiting.values():
            if u.role == peer_role and u.status == Status.Prepared.name:
                return u
        else:
            return None

    def _find_peer_ai(user: UserDef) -> AssistantDef:
        if user.role != "保健師":
            return None
        return AssistantDef(
                user_id = get_id(),
                role = "患者",
                assistant_id = choice(config.assistant_list),
                )

    def _find_user_session(user: UserDef) -> Session:
        for s in users_session.values():
            for u in s.users:
                if u.user_id == user.user_id:
                    return s
        else:
            return None

    async def _session_human(user: UserDef, db: Session):
        try:
            while True:
                data = await user.ws.receive_json()
                if data["msg_type"] == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    session = users_session.get(m.session_id)
                    if session is not None:
                        await log_message(db, session.session_id, user.user_name, user.target_patient_id, user.role, "User", m.user_msg)

                        for u in session.users:
                            if u.user_id == m.user_id:
                                session.history.history.append(
                                        MessageInfo.model_validate({
                                            "role": u.role,
                                            "text": m.user_msg
                                            }))
                            else:
                                await log_message(db, session.session_id, u.user_name, u.target_patient_id, u.role, "Assistant", m.user_msg)
                                await u.ws.send_json(
                                        MessageForwarded(
                                            session_id=m.session_id,
                                            user_msg=m.user_msg
                                        ).dict())
                    else:
                        await user.ws.send_json(
                                MessageRejected(
                                    reason="ERROR: Invalid Session ID",
                                ).dict())
                elif data["msg_type"] == MsgType.EndSessionRequest.name:
                    m = EndSessionRequest.model_validate(data)
                    session = users_session.get(m.session_id)
                    if session is not None:
                        for u in session.users:
                            if u.ws is None:
                                continue
                            if u.user_id == m.user_id:
                                # close my session
                                await u.ws.send_json(
                                        SessionTerminated(
                                            session_id=m.session_id,
                                            reason="EndSession request is accpepted.",
                                        ).dict())
                            else:
                                # close peer's session
                                await u.ws.send_json(
                                        SessionTerminated(
                                            session_id=m.session_id,
                                            reason="Peer sent the end of session.",
                                        ).dict())
                            await u.ws.close()
                        # store history
                        await _save_history(m.session_id, session.history)
                        del users_session[m.session_id]
                        break
                    else:
                        await user.ws.send_json(
                                MessageRejected(
                                    reason="ERROR: Invalid Message Type",
                                ).dict())
                else:
                    await user.ws.send_json(
                            MessageRejected(
                                reason="ERROR: Invalid Message Type",
                            ).dict())

        except WebSocketDisconnect as e:
            logger.debug(f"WS Exception: {user.user_id} {e}")
            s = _find_user_session(user)
            if s is not None:
                for peer in s.users:
                    if peer.user_id != user.user_id:
                        await peer.ws.send_json(
                                SessionTerminated(
                                    session_id=s.session_id,
                                    reason="Peer sent the end of session.",
                                ).dict())
                user.ws = None
            # delete session and userdef
            del s

    async def _session_ai(user: UserDef, db: Session):
        #try:
        if True:
            while True:
                data = await user.ws.receive_json()
                if data["msg_type"] == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    session = users_session.get(m.session_id)
                    if session is not None:
                        await log_message(db, session.session_id, user.user_name, user.target_patient_id, user.role, "User", m.user_msg)

                        for u in session.users:
                            if u.user_id == m.user_id:
                                session.history.history.append(
                                        MessageInfo.model_validate({
                                            "role": u.role,
                                            "text": m.user_msg
                                            }))
                                continue
                            if u.model_dump().get("thread_id") is not None:
                                # send message to AI
                                response_msg = await oaw.send_message(u, m.user_msg)
                                # add response to history
                                session.history.history.append(
                                        MessageInfo.model_validate({
                                            "role": u.role,
                                            "text": response_msg,
                                            }))
                                await log_message(db, session.session_id, "AI", u.assistant_id, u.role, "Assistant", response_msg)
                                # reply to Human
                                await user.ws.send_json(
                                    MessageForwarded(
                                        session_id=m.session_id,
                                        user_msg=response_msg,
                                    ).dict())
                    else:
                        await user.ws.send_json(
                                MessageRejected(
                                    reason="ERROR: Invalid Session ID",
                                ).dict())
                elif data["msg_type"] == MsgType.EndSessionRequest.name:
                    m = EndSessionRequest.model_validate(data)
                    session = users_session.get(m.session_id)
                    if session is not None:
                        for u in session.users:
                            if u.user_id == m.user_id:
                                await u.ws.send_json(
                                        SessionTerminated(
                                            session_id=m.session_id,
                                            reason="End Session is accepted.",
                                        ).dict())
                                await u.ws.close()
                                continue
                            if u.model_dump().get("thread_id") is not None:
                                # close AI session
                                status = await oaw.delete_thread(u)
                                logger.debug(f"OPENAI Delete Thread {status}")
                        # store history
                        await _save_history(m.session_id, session.history)
                        del users_session[m.session_id]
                        break
                    else:
                        # silently discard.
                        logger.debug("EndSessionRequest was received, "
                                     "but the session doesn't exist "
                                     f"{m.session_id}")
                        pass
                else:
                    await user.ws.send_json(
                            MessageRejected(
                                reason="ERROR: Invalid Message Type",
                            ).dict())
        """
        except Exception as e:
            print(e)
            # If a user disconnects, remove them from the dictionary
            await user.ws.close()
            del users[user_id]
        """

    def _registration(req: RegistrationRequest, db: Session):
        user_id = get_id()
        session_id = str(uuid.uuid4())
        #
        users_waiting[user_id] = UserDef(
                user_id=user_id,
                user_name=req.user_name,
                role=req.user_role,
                status=Status.Registered.name,
                target_patient_id=req.target_patient_id,
                )
        #
        return RegistrationAccepted(
            user_id=user_id,
            session_id=session_id,
            )
    #
    # API
    #
    """
    Initial -> Registered
    """
    @app.get("/v1/patients")
    async def get_available_patients():
        """利用可能な患者IDのリストを返すエンドポイント"""
        if role_provider.df is None:
            # まだ初期化が完了していない、または失敗した場合
            logger.warning("Patient data is not available yet.")
            raise HTTPException(status_code=503, detail="Patient data is not ready. Please try again later.")
        
        ids = role_provider.get_available_patient_ids()
        return {"patient_ids": ids}

    @app.get("/v1/patient/{patient_id}")
    async def get_patient_details(patient_id: str):
        """指定された患者IDの詳細情報を返すエンドポイント"""
        if role_provider.df is None:
            logger.warning("Patient data is not available yet.")
            raise HTTPException(status_code=503, detail="Patient data is not ready. Please try again later.")
        
        details = role_provider.get_patient_details(patient_id)
        if "error" in details:
            logger.error(f"Error getting patient details for ID {patient_id}: {details['error']}")
            raise HTTPException(status_code=404, detail=details['error'])
        
        return details

    @app.post("/v1")
    async def post_request(req: RegistrationRequest, db: Session = Depends(get_db)):
        logger.debug(f"APP POST REQ: {req}")
        if req.msg_type == MsgType.RegistrationRequest.name:
            return _registration(req, db)
        """
        else:
            raise HTTPException(status_code=httpcode.HTTP_406_NOT_ACCEPTABLE,
                                detail=RegistrationRejected(
                                    msg_type=MsgType.RegistrationRejected.name,
                                    user_status=status.name
                                ))
        """

    """
    Registered -> Prepared
               -> Established
    """
    @app.websocket("/v1/ws/{user_id}")
    async def websocket_endpoint(user_id: str, ws: WebSocket, db: Session = Depends(get_db)):
        print(f"user_id: {user_id}")
        if users_waiting.get(user_id) is None:
            return PreparationRejected(
                    reason=f"Invalid user ID {user_id}"
                    )

        try:
            await ws.accept()

            user = users_waiting[user_id]
            user.ws = ws
            user.status = Status.Prepared.name

            peer = _find_peer_human(user)
            if peer:
                # make a session
                session_id = get_id()
                users_session[session_id] = Session.model_validate({
                    "users": [user, peer],
                    "history": History.model_validate({}),
                    "session_id": session_id,
                    })
                del users_waiting[user.user_id]
                del users_waiting[peer.user_id]
                # vs human
                peer.status = Status.Established.name
                await peer.ws.send_json(
                    Established(session_id=session_id).dict()
                    )
                #
                user.status = Status.Established.name
                await user.ws.send_json(
                    Established(session_id=session_id).dict()
                    )
                await _session_human(user, db)
            else:
                assistant = _find_peer_ai(user)
                if assistant:
                    session_id = get_id()
                    history = History.model_validate({
                            "assistant": {
                                "role": "患者",
                                "assistant_id": assistant.assistant_id,
                            }})
                    users_session[session_id] = Session.model_validate({
                        "users": [user, assistant],
                        "history": history,
                        "session_id": session_id,
                        })
                    del users_waiting[user.user_id]
                    # vs ai
                    user.status = Status.Established.name
                    assistant.thread_id = await oaw.create_thread()
                    logger.debug(f"Created new thread with ID: {assistant.thread_id}")

                    # ペルソナを最初のメッセージとして注入
                    if role_provider.df is not None:
                        # 保健師が指定した患者ID、またはデフォルトID "1" を使用
                        patient_id_for_ai = user.target_patient_id or "1"
                        prompt_chunks = role_provider.get_patient_prompt_chunks(patient_id_for_ai)
                        
                        for chunk in prompt_chunks:
                            # OpenAIのスレッドに注入
                            await oaw.add_message_to_thread(assistant.thread_id, chunk)
                            # ローカルのhistoryにも記録
                            history.history.append(
                                MessageInfo(role="system", text=chunk)
                            )
                            await log_message(db, session_id, user.user_name, patient_id_for_ai, user.role, "System", chunk)
                        logger.debug(f"Persona chunks injected for patient ID {patient_id_for_ai}")

                        # アシスタントの初期発言を追加
                        initial_bot_message = "何でも聞いてください"
                        history.history.append(
                            MessageInfo(role="患者", text=initial_bot_message)
                        )
                        await log_message(db, session_id, "AI", patient_id_for_ai, "患者", "Assistant", initial_bot_message)
                        # 人間のクライアントに初期発言を送信
                        await user.ws.send_json(
                            MessageForwarded(
                                session_id=session_id,
                                user_msg=initial_bot_message
                            ).dict()
                        )
                    else:
                        logger.warning("PatientRoleProvider is not initialized. Skipping persona injection.")

                    await user.ws.send_json(
                        Established(session_id=session_id).dict()
                        )
                    await _session_ai(user, db)
                else:
                    # prepare to make a sessoin with a human.
                    await user.ws.send_json(
                            Prepared().dict()
                            )
                    await _session_human(user, db)
        except WebSocketDisconnect as e:
            logger.debug(f"WS Exception: {user.user_id} {e}")

    #
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=config.www_path, html=True),
              name="www")

    #
    return app
