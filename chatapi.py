from fastapi import FastAPI, Body, Request, HTTPException
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import status as httpcode
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from typing import Union
from modelChat import *
from modelUserDef import *
import aiofile
import dateutil.parser
import asyncio
from openai_assistant import OpenAIAssistantWrapper
from uuid import uuid4
from datetime import datetime
from random import random, choice
from hashlib import sha1

def api(config):

    logger = config.logger

    config.queue = asyncio.Queue(maxsize=config.max_queue_size)
    config.queue._loop = config.loop
    # create OpenAI API wrapper
    oaw = OpenAIAssistantWrapper(config)

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
    users ={ <user_id>: UserDef }
    UserDef:
        user_id: str
        role: str
        status: str
        ws: ws
        peer: Union[UserDef
    """
    users = {}

    def get_user_id() -> str:
        base = f"{datetime.now().timestamp()}-{random()}"
        return sha1(base.encode()).hexdigest()

    def _find_peer_human(user: UserDef):
        # find a peer
        if user.role == "患者":
            peer_role = "保健師"
        elif user.role == "保健師":
            peer_role = "患者"
        else:
            raise ValueError(f"ERROR: invalid user role {user.role}")

        for u in users.values():
            if u.role == peer_role and u.status == Status.Prepared.name:
                return u
        else:
            return None

    def _find_peer_ai(user: UserDef):
        if user.role != "保健師":
            return None
        assistants = [
                "asst_3QFD4I5A1io0Xi8iCwgUGVHA",
                ]
        return AIPatient(
                user_id = get_user_id(),
                patient_id = choice(assistants),
                )

    async def _session_human(user: UserDef):
        #try:
        if True:
            while True:
                data = await user.ws.receive_json()
                if data["msg_type"] == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    peer = users[m.user_id].peer
                    if peer is not None:
                        await peer.ws.send_json(
                                MessageForwarded(
                                    peer_id=m.user_id,
                                    user_msg=m.user_msg
                                ).dict())
                    else:
                        raise ValueError(f"ERROR: peer doesn't exit {user}")
                elif data["msg_type"] == MsgType.EndSessionRequest.name:
                    m = EndSessionRequest.model_validate(data)
                    user = users.get(m.user_id)
                    if user is None:
                        await user.ws.send_json(
                                MessageRejected(
                                    reason="ERROR: Invalid Message Type",
                                ).dict())
                    else:
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
                        await user.ws.send_json(
                                SessionTerminated(
                                    reason="EndSessionRequest is accepted.",
                                ).dict())
                        await user.ws.close()
                        del users[user.user_id]
                        break
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
                    response_msg = await oaw.send_message(user.peer, m.user_msg)
                    await user.ws.send_json(
                            MessageForwarded(
                                peer_id=user.peer.user_id,
                                user_msg=response_msg,
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
        for i in range(3):
            user_id = get_user_id()
            if not users.get(user_id):
                break
        else:
            return Rejected(
                msg_type=MsgType.RegistrationRejected.name,
                user_status=Status.Initial.name,
                )
        #
        users[user_id] = UserDef(
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
        if users.get(user_id) is None:
            return PreparationRejected(
                    reason=f"Invalid user ID {user_id}"
                    )

        try:
            await ws.accept()

            user = users[user_id]
            user.ws = ws
            user.status = Status.Prepared.name

            peer = _find_peer_human(user)
            if peer:
                # vs human
                peer.status = Status.Established.name
                peer.peer = user
                await peer.ws.send_json(
                    Established(peer_id=user.user_id).dict()
                    )
                #
                user.status = Status.Established.name
                user.peer = peer
                await user.ws.send_json(
                    Established(peer_id=peer.user_id).dict()
                    )
                await _session_human(user)
            else:
                peer = _find_peer_ai(user)
                if peer:
                    # vs ai
                    user.status = Status.Established.name
                    user.peer = peer
                    peer.thread_id = await oaw.create_thread()
                    await user.ws.send_json(
                        Established(peer_id=user.peer.user_id).dict()
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

