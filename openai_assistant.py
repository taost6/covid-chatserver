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

    async def add_message_to_thread(self, thread_id: str, message_text: str):
        """
        指定されたスレッドに、'user'ロールでメッセージを追加する。
        これはAIへの初期指示（ペルソナ設定）を注入するために使用する。
        """
        thread_message = await self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user", # 'system'ロールはAPIでサポートされていないため'user'として送信
            content=message_text,
        )
        return thread_message

    async def send_message(self,
                           assistant: AssistantDef,
                           request_text: str,
                           ) -> str:
            # ユーザーからのメッセージをスレッドに追加
            await self.add_message_to_thread(assistant.thread_id, request_text)
            
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
                            thread_id=assistant.thread_id,
                            order="desc", # 最新のメッセージを先頭に
                            limit=1
                            )
                    # 最新のメッセージがアシスタントからのものであることを確認
                    if messages.data and messages.data[0].role == "assistant":
                        assistant_response = messages.data[0].content[0].text.value
                        print(f"Assistant response: {assistant_response}")
                        return assistant_response
                    else:
                        # 予期せぬ状況（アシスタントの応答がないなど）
                        print("Assistant response not found or not the latest message.")
                        return "FAILED: No response from assistant."

                elif res.status in failed_status:
                    messages = await self.client.beta.threads.messages.list(
                            thread_id=assistant.thread_id)
                    print(f"Assistant response FAILED: {messages}")
                    return "FAILED"

                await sleep(1)
