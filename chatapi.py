from fastapi import FastAPI, Body, Request, HTTPException, WebSocket
from fastapi import status as httpcode
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from typing import Union
from modelChat import *
import aiofile
import dateutil.parser
import asyncio
#from mmworker import SendMessage
from uuid import uuid4
from enum import Enum, auto

class MsgType(Enum):
    RegistrationRequest = 0
    Registered = 1
    Prepared = 2
    Establised = 3
    MessageSubmitted = 201
    MessageForwarded = 202
    RegistrationRejected = 401
    PreparationRejected = 402

class Status(Enum):
    Initial = 1
    Registered = 2
    Prepared = 3
    Established = 4

def api(config):

    logger = config.logger

    config.queue = asyncio.Queue(maxsize=config.max_queue_size)
    config.queue._loop = config.loop
    # create sendmsg object.
    #sendmsg = SendMessage(config)
    # start sendmsg worker.
    #config.loop.create_task(sendmsg.worker())

    #xtmap = XTokenMap()
    users = {}
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
        peer: UserDef
    """
    users = {}

    def _find_peer(user):
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

    async def _preparation(user: UserDef):
        peer = _find_peer(user)
        if peer is not None:
            #
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
        else:
            await user.ws.send_json(
                    Prepared().dict()
                    )

    def _registration(req: RegistrationRequest):
        for i in range(3):
            user_id = str(uuid4())
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
        return Registered(
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

        await ws.accept()

        user = users[user_id]
        user.ws = ws
        user.status = Status.Prepared.name

        await _preparation(user)

        #try:
        if True:
            while True:
                data = await ws.receive_json()
                print("xxx", data)
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
                    await ws.send_json(
                            MessageRejected(
                                reason="ERROR: Invalid Message Type",
                            ).dict())
        """
        except Exception as e:
            print(e)
            # If a user disconnects, remove them from the dictionary
            await ws.close()
            del users[user_id]
        """

    """
    """
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=config.www_path, html=True),
              name="www")

    #
    return app

