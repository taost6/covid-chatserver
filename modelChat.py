from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Union, List, Optional, Any
from enum import Enum

"""
## 状態遷移

A. ユーザがサーバにアクセスする。
    - ユーザの状態は**Initial**になる。
        - Initialの状態は内部的には何もない。
    - Bに移行できる。

B. ユーザがロールを登録する。
    - ユーザの状態は**Initial**であること。
        - Initialの状態は内部的には何もない。
    - ユーザが*Registration Request*をシステムに送信する。
        - 相手をシステムに任せるか、自分で選ぶかを指定する。
        - 保健師か患者を指定する。(予定)
    - 登録が成功すると、システムは*Registration Succeeded*をユーザに送信する。
    - ユーザの状態は**Registered**になる。
    - Cに移行できる。

C. ユーザとのWebSocketセッションを開始する。
    - ユーザの状態は**Registered**であること。
    - ユーザからのWS接続要求に従ってWSセッションを開始する。
    - ユーザの状態は**Prepared**になる。
    - Dに移行できる。
    - 登録に失敗すると、システムは*Preparation Rejected*をユーザに送信する。

D. ユーザの相手を見つける。
    - ユーザの状態は**Prepared**であること。
    - 相手を見つけると、システムは*Establishment Succeeded*を双方に送信する。
    - ユーザの状態は**Established**になる。
    - Eに移行できる。

Z. セッションを終了する。
    - ユーザは*EndSession Request*をシステムに送信する。

## Function Code (msg_type)

## User Id (user_id)

- 0: system
- others: user

## Session Id (session_id)

- 0: system
- others: user's session

## User Role (user_role)

- 保健師
- 患者

## Status (user_status)

- System
    - システムの状態。常に一定。
- Initial
    - ユーザの状態。初期状態。
    - Registrationが成功するとPreparedになる。
- Prepared
    - ユーザの状態。user_roleを登録した状態。
    - Unregisterationが成功するとInitialになる。
- Established
    - ユーザの状態。相手がいる状態。

"""

class MsgType(Enum):
    RegistrationRequest = 0
    RegistrationAccepted = 1
    Prepared = 2
    Established = 3
    EndSessionRequest = 4
    SessionTerminated = 5
    DebriefingRequest = 6
    DebriefingResponse = 7
    ToolCallDetected = 8
    ContinueConversationRequest = 9
    ConversationContinueAccepted = 10
    MessageSubmitted = 201
    MessageForwarded = 202
    MessageRejected = 203
    RegistrationRejected = 401
    PreparationRejected = 402

class Status(Enum):
    Initial = 1
    Registered = 2
    Prepared = 3
    Established = 4

# C > S
class RegistrationRequest(BaseModel):
    msg_type: str=MsgType.RegistrationRequest.name
    user_name: str
    user_role: Literal["保健師", "患者"]
    target_patient_id: Optional[str] = Field(None,
            description="保健師が対話したい患者のID")

# S > U
class RegistrationAccepted(BaseModel):
    msg_type: str=MsgType.RegistrationAccepted.name
    user_status: str=Status.Prepared.name
    user_id: str
    session_id: str

# S > U
class RegistrationRejected(BaseModel):
    msg_type: str=MsgType.RegistrationRejected.name
    user_status: str=Status.Initial.name

# S > U
class Prepared(BaseModel):
    msg_type: str=MsgType.Prepared.name
    user_status: str=Status.Prepared.name

# S > U
class PreparationRejected(BaseModel):
    msg_type: str=MsgType.PreparationRejected.name
    user_status: str=Status.Registered.name
    reason: str

# S > U
class Established(BaseModel):
    msg_type: str=MsgType.Established.name
    user_status: str=Status.Established.name
    session_id: str
    interview_date: Optional[str] = None

# U > S
class MessageSubmitted(BaseModel):
    msg_type: str=MsgType.MessageSubmitted.name
    session_id: str
    user_id: str
    user_msg: str

# S > U
class MessageForwarded(BaseModel):
    msg_type: str=MsgType.MessageForwarded.name
    session_id: str
    user_msg: str

# S > U
class MessageRejected(BaseModel):
    msg_type: str=MsgType.MessageRejected.name
    session_id: str
    reason: str

# U > S
class EndSessionRequest(BaseModel):
    msg_type: str=MsgType.EndSessionRequest.name
    session_id: str
    user_id: str

# S > U
class SessionTerminated(BaseModel):
    msg_type: str=MsgType.SessionTerminated.name
    session_id: str
    reason: str

# U > S
class DebriefingRequest(BaseModel):
    msg_type: str=MsgType.DebriefingRequest.name
    session_id: str
    user_id: str

# S > U
class DebriefingResponse(BaseModel):
    msg_type: str=MsgType.DebriefingResponse.name
    session_id: str
    debriefing_data: dict

# S > U
class ToolCallDetected(BaseModel):
    msg_type: str=MsgType.ToolCallDetected.name
    session_id: str

# U > S
class ContinueConversationRequest(BaseModel):
    msg_type: str=MsgType.ContinueConversationRequest.name
    session_id: str
    user_id: str

# S > U
class ConversationContinueAccepted(BaseModel):
    msg_type: str=MsgType.ConversationContinueAccepted.name
    session_id: str

if __name__ == "__main__":
    RegistrationRequest.model_validate({
        "msg_type": "Registration Request",
        "user_role": "保健師"
        })
