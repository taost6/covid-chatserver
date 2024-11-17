from fastapi import FastAPI, Body, Request, HTTPException
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import status as httpcode
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List
from modelChat import *
from modelUserDef import *
from modelHistory import *
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

def api(config):

    logger = config.logger

    config.queue = asyncio.Queue(maxsize=config.max_queue_size)
    config.queue._loop = config.loop
    # create OpenAI API wrapper
    oaw = OpenAIAssistantWrapper(config)
    # 
    config.assistant_list = json.load(open(config.assistants_storage,
                                           encoding="utf-8"))

    app = FastAPI()

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

    async def _save_history(session_id: str, history: History) -> None:
        filename = f"history-{session_id}.json"
        async with aiofiles.open(filename, "w", encoding="utf-8") as fd:
            await fd.write(json.dumps(history.model_dump(), ensure_ascii=False))
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

    async def _session_human(user: UserDef):
        #try:
        if True:
            while True:
                data = await user.ws.receive_json()
                if data["msg_type"] == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    session = users_session.get(m.session_id)
                    if session is not None:
                        for u in session.users:
                            if u.user_id == m.user_id:
                                session.history.history.append(
                                        MessageInfo.model_validate({
                                            "role": u.role,
                                            "text": m.user_msg
                                            }))
                            else:
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

        """
        except Exception as e:
            logger.debug(f"WS Exception: {user.user_id}")
            # close peer's ws session
            if user.peer is not None:
                await user.peer.ws.send_json(
                        SessionTerminated(
                            reason="Peer sent the end of session.",
                        ).dict())
                await user.peer.ws.close()
                user.peer.peer = None
                del users[user.peer.user_id]
                user.peer = None
            # close user's ws session
            if users.get(user.user_id):
                del users[user.user_id]
        """

    async def _session_ai(user: UserDef):
        #try:
        if True:
            while True:
                data = await user.ws.receive_json()
                if data["msg_type"] == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    session = users_session.get(m.session_id)
                    if session is not None:
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
                                response_msg = await oaw.send_message(
                                        u, m.user_msg)
                                # add response to history
                                session.history.history.append(
                                        MessageInfo.model_validate({
                                            "role": u.role,
                                            "text": response_msg,
                                            }))
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
                        await user.ws.send_json(
                                MessageRejected(
                                    reason="ERROR: Invalid Message Type",
                                ).dict())
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

    def _registration(req: RegistrationRequest):
        user_id = get_id()
        #
        users_waiting[user_id] = UserDef(
                user_id=user_id,
                role=req.user_role,
                status=Status.Registered.name,
                )
        #
        return RegistrationAccepted(
            #msg_type=MsgType.Registered.name,
            #user_status=Status.Registered.name,
            user_id=user_id,
            )
    #
    # API
    #
    """
    Initial -> Registered
    """
    @app.post("/v1")
    async def post_request(req: RegistrationRequest):
        logger.debug(f"APP POST REQ: {req}")
        if req.msg_type == MsgType.RegistrationRequest.name:
            return _registration(req)
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
    async def websocket_endpoint(user_id: str, ws: WebSocket):
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
                    "history": History.model_validate({})
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
                await _session_human(user)
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
                        })
                    del users_waiting[user.user_id]
                    # vs ai
                    user.status = Status.Established.name
                    assistant.thread_id = await oaw.create_thread()
                    await user.ws.send_json(
                        Established(session_id=session_id).dict()
                        )
                    await _session_ai(user)
                else:
                    # prepare to make a sessoin with a human.
                    await user.ws.send_json(
                            Prepared().dict()
                            )
                    await _session_human(user)
        except WebSocketDisconnect as e:
            logger.debug(f"WS Exception: {user.user_id} {e}")

    #
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=config.www_path, html=True),
              name="www")

    #
    return app

