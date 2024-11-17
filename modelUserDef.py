from pydantic import BaseModel, Field
from typing import Literal, Union, List, Optional, Any

class AIPatient(BaseModel):
    user_id: str    = Field(description="Identifier exposed to the peer")
    patient_id: str = Field(description="Patient ID to be communicated.")
    thread_id: Optional[str] = Field(None,
            description="Thread Idenfifier of OpenAI API")

class UserDef(BaseModel):
    user_id: str   = Field(description="User ID")
    role: str      = Field(description="User Role")
    status: str    = Field(description="User Status")
    ws: Any = None = Field(description="Placeholder of WebSocket session")

if __name__ == "__main__":
    AIPatient(user_id="aaa", patient_id="bbb")
    AIPatient(user_id="aaa", patient_id="bbb", thread_id="ccc")
