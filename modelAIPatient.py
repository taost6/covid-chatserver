from pydantic import BaseModel, Field
from typing import Literal, Union, List, Optional, Any

class AIPatient(BaseModel):
    user_id: str    = Field(description="Identifier exposed to the peer")
    patient_id: str = Field(description="Patient ID to be communicated.")
    thread_id: str  = Field(description="Thread Idenfifier of OpenAI API")

