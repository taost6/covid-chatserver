from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Union, Any

class MessageInfo(BaseModel):
    role: Literal["保健師","患者"] = Field(
            description="Role name of the entiry submitted the request.")
    text: str = Field(
            description="text message in the request or response.")

class AssistantInfo(BaseModel):
    assistant_id: str = Field(
            description="Assistant ID.")
    role: Literal["保健師","患者"] = Field(
            description="Assistant's role")

class History(BaseModel):
    assistant: Optional[AssistantInfo] = Field(None,
            description="Assistant information if Assistant helps for any of roles.")
    history: Optional[List[MessageInfo]] = Field([],
            description="a list of the messages.")

if __name__ == "__main__":
    sample_msginfo = [
        {
            "role": "保健師",
            "text": "aaa"
        },
        {
            "role": "患者",
            "text": "bbb"
        },
        ]
    sample_assistantinfo = [
        {
            "assistant_id": "aaa",
            "role": "保健師"
        },
        {
            "assistant_id": "bbb",
            "role": "患者"
        },
        ]
    sample_history = [
        {
            "assistant": None,
            "history": sample_msginfo,
        },
        {
            "history": sample_msginfo,
        },
        {
            "assistant": sample_assistantinfo[0],
            "history": sample_msginfo,
        },
        {
            "assistant": sample_assistantinfo[0],
            "history": [],
        },
        {
            "history": [],
        },
        {
        },
    ]
    for v in sample_msginfo:
        print(MessageInfo.model_validate(v))
    for v in sample_assistantinfo:
        print(AssistantInfo.model_validate(v))
    for v in sample_history:
        print(History.model_validate(v))

    x = History.model_validate(sample_history[2])
    m = MessageInfo.model_validate(sample_msginfo[0])
    print(x)
    print(m)
    x.history.append(m)
    print(x)

