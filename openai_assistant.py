from pydantic import BaseModel
from modelUserDef import AIPatient
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

    async def send_message(self,
                           thread: AIPatient,
                           request_text: str,
                           ) -> str:
            thread_message = await self.client.beta.threads.messages.create(
                thread_id=thread.thread_id,
                role="user",
                content=request_text,
            )
            run = await self.client.beta.threads.runs.create_and_poll(
                thread_id=thread.thread_id,
                assistant_id=thread.patient_id,
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
                    thread_id=thread.thread_id,
                    run_id=run.id
                )
                print(res.status)

                if res.status == "completed":
                    messages = await self.client.beta.threads.messages.list(thread_id=thread.thread_id)
                    assistant_response = messages.data[0].content[0].text.value
                    print(f"Assistant response: {assistant_response}")
                    return assistant_response
                elif res.status in failed_status:
                    messages = await self.client.beta.threads.messages.list(thread_id=thread.thread_id)
                    print(f"Assistant response FAILED: {messages}")
                    return "FAILED"

                await sleep(1)

