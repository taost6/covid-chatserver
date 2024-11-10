from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class MessageInfo(BaseModel):
    role: Literal["user","assistant"] = Field(
            description="Role name of the entiry submitted the request.")
    text: str = Field(
            description="text message in the request or response.")

class History(BaseModel):
    assistant_id: str = Field(
            description="Assistant ID.")
    history: List[MessageInfo] = Field(
            description="a list of the messages.")

if __name__ == "__main__":
    sample_msginfo = {
        "role": "assistant",
        "text": "bbb"
    }
    sample_history = {
        "assistant_id": "xxx",
        "history": [
            {
                "role": "user",
                "text": "aaa"
            },
            {
                "role": "assistant",
                "text": "bbb"
            },
        ]
    }
    print(MessageInfo.model_validate(sample_msginfo))
    print(History.model_validate(sample_history))

