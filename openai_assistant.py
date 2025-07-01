import logging
from pydantic import BaseModel
from modelUserDef import AssistantDef
from openai import AsyncOpenAI
from openai_etc import openai_get_apikey
from typing import Optional, Any
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
                           ) -> (Optional[str], Optional[Any]):
            # ツール（関数）の定義
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "end_conversation_and_start_debriefing",
                        "description": "ユーザーが会話の終了を望んでいると判断した場合に、会話を終了し、評価フェーズを開始します。",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
            ]

            # ユーザーからのメッセージをスレッドに追加
            await self.add_message_to_thread(assistant.thread_id, request_text)
            
            run = await self.client.beta.threads.runs.create_and_poll(
                thread_id=assistant.thread_id,
                assistant_id=assistant.assistant_id,
                tools=tools,
                truncation_strategy={
                    "type": "auto",
                    "last_messages": None,
                },
            )

            if run.status == 'completed':
                messages = await self.client.beta.threads.messages.list(
                    thread_id=assistant.thread_id,
                    order="desc",
                    limit=1
                )
                if messages.data and messages.data[0].role == "assistant":
                    assistant_response = messages.data[0].content[0].text.value
                    return assistant_response, None
                else:
                    return "FAILED: No response from assistant.", None

            elif run.status == 'requires_action':
                # Tool Callingが要求された場合
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                if tool_calls:
                    tool_outputs = []
                    for tool_call in tool_calls:
                        # 各ツールコールに対して、空の成功を示す出力を生成
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": "{\"success\": true}", # JSON形式の文字列として成功レスポンス
                        })
                    
                    # ツール実行結果を送信してRunを継続
                    await self.client.beta.threads.runs.submit_tool_outputs_and_poll(
                        thread_id=assistant.thread_id,
                        run_id=run.id,
                        tool_outputs=tool_outputs
                    )
                    # この関数呼び出しがdebriefingのトリガーなので、tool_callオブジェクトを返す
                    return None, tool_calls[0]
                else:
                    return "FAILED: Tool call required but no tool_calls found.", None

            else: # failed, cancelled, expired
                logging.error(f"Run failed with status: {run.status}")
                if run.last_error:
                    logging.error(f"Run last_error: {run.last_error}")
                logging.error(f"Run object: {run}")
                return "FAILED", None
