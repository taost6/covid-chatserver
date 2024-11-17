from pydantic import BaseModel
from modelUserDef import AssistantDef
from openai import AsyncOpenAI
from openai_etc import openai_get_apikey
from typing import Optional
from asyncio import sleep as sleep

class OpenAIAssistantWrapper():
    def __init__(self, config):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=openai_get_apikey(config.apikey_storage)
        )

    async def create_thread(self):
        thread = await self.client.beta.threads.create()
        return thread.id

    async def delete_thread(self, assistant: AssistantDef):
        status = await self.client.beta.threads.delete(assistant.thread_id)
        return status

    async def send_message(self,
                           assistant: AssistantDef,
                           request_text: str,
                           ) -> str:
            thread_message = await self.client.beta.threads.messages.create(
                thread_id=assistant.thread_id,
                role="user",
                content=request_text,
            )
            run = await self.client.beta.threads.runs.create_and_poll(
                thread_id=assistant.thread_id,
                assistant_id=assistant.assistant_id,
                truncation_strategy={
                    "type": "auto",
                    "last_messages": None,
                },
            )
            failed_status = [
                    "requires_action",
                    "cancelled",
                    "failed",
                    "expired",
                    "incomplete"
                    ]
            while True:
                res = await self.client.beta.threads.runs.retrieve(
                    thread_id=assistant.thread_id,
                    run_id=run.id
                )
                print(res.status)

                if res.status == "completed":
                    messages = await self.client.beta.threads.messages.list(
                            thread_id=assistant.thread_id)
                    assistant_response = messages.data[0].content[0].text.value
                    print(f"Assistant response: {assistant_response}")
                    return assistant_response
                elif res.status in failed_status:
                    messages = await self.client.beta.threads.messages.list(
                            thread_id=assistant.thread_id)
                    print(f"Assistant response FAILED: {messages}")
                    return "FAILED"

                await sleep(1)

