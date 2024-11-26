from pydantic import BaseModel, Field
from typing import Literal, Union, List, Optional, Any

class AssistantDef(BaseModel):
    user_id: str      = Field(description="Identifier exposed to the peer")
    role: Literal["保健師","患者"] = Field(description="Assistant Role")
    assistant_id: str = Field(description="Assistant ID to be communicated.")
    thread_id: Optional[str] = Field(None,
            description="Thread Idenfifier of OpenAI API")

class UserDef(BaseModel):
    user_id: str = Field(description="User ID")
    role: Literal["保健師","患者"] = Field(description="Assistant Role")
    status: str  = Field(description="User Status")
    ws: Any      = Field(None, description="Placeholder of WebSocket")
    # session をここでも管理すると便利かも
    #session: Any = Field(None, description="Placeholder of the session")

if __name__ == "__main__":
    AssistantDef(user_id="aaa", role="患者", assistant_id="bbb")
    a = AssistantDef(user_id="aaa", role="患者", assistant_id="bbb",
                     thread_id="ccc")
    a.model_dump().get("user_id")
