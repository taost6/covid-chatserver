from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Union, List, Optional, Any

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

# C > S
class RegistrationRequest(BaseModel):
    msg_type: str="RegistrationRequest"
    user_role: Literal["保健師", "患者"]

# S > U
class Registered(BaseModel):
    msg_type: str="RegistrationSuccessful"
    user_status: str="Prepared"
    user_id: str

# S > U
class RegistrationRejected(BaseModel):
    msg_type: str="RegistrationRejected"
    user_status: str="Initial"

# S > U
class Prepared(BaseModel):
    msg_type: str="Prepared"
    user_status: str="Prepared"

# S > U
class PreparationRejected(BaseModel):
    msg_type: str="PreparationRejected"
    user_status: str="Registered"
    reason: str

# S > U
class Established(BaseModel):
    msg_type: str="Established"
    user_status: str="Established"
    peer_id: str

# U > S
class MessageSubmitted(BaseModel):
    msg_type: str="MessageSubmitted"
    user_id: str
    user_msg: str

# S > U
class MessageForwarded(BaseModel):
    msg_type: str="MessageForwarded"
    peer_id: str
    user_msg: str

# S > U
class MessageRejected(BaseModel):
    msg_type: str="MessageRejected"
    reason: str

# U > S
class EndSessionRequest(BaseModel):
    msg_type: str="EndSessionRequest"

if __name__ == "__main__":
    RegistrationRequest.model_validate({
        "msg_type": "Registration Request",
        "user_role": "保健師"
        })

