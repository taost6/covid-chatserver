from pydantic import BaseModel, Field
from typing import Literal, Union, List, Optional, Any
from modelAIPatient import AIPatient

class UserDef(BaseModel):
    user_id: str
    role: str
    status: str
    ws: Any = None
    peer: Optional[Union["UserDef",AIPatient]] = Field(
            None,
            description="placeholder of the peer information.")

