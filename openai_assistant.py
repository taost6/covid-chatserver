import logging
from pydantic import BaseModel
from modelUserDef import AssistantDef
from openai import AsyncOpenAI
from openai_etc import openai_get_apikey
from typing import Optional, Any, List
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

    async def get_assistant_info(self, assistant_id: str):
        """
        指定されたAssistant IDの情報を取得する
        """
        try:
            logging.info(f"Retrieving assistant info for ID: {assistant_id}")
            assistant = await self.client.beta.assistants.retrieve(assistant_id)
            
            result = {
                "model": assistant.model,
                "name": assistant.name,
                "description": assistant.description,
                "instructions": assistant.instructions
            }
            
            logging.info(f"Successfully retrieved assistant info for {assistant_id}: model={assistant.model}, name={assistant.name}")
            return result
            
        except Exception as e:
            logging.error(f"Failed to get assistant info for {assistant_id}: {e}", exc_info=True)
            return None

    async def delete_thread(self, assistant: AssistantDef):
        status = await self.client.beta.threads.delete(assistant.thread_id)
        return status

    async def delete_thread_by_id(self, thread_id: str):
        """thread_idから直接スレッドを削除する"""
        if not thread_id:
            return None
        status = await self.client.beta.threads.delete(thread_id)
        return status

    async def cancel_run(self, thread_id: str):
        try:
            runs = await self.client.beta.threads.runs.list(thread_id=thread_id, limit=10)
            for run in runs.data:
                if run.status in ['queued', 'in_progress', 'requires_action']:
                    logging.info(f"Cancelling active run {run.id} with status {run.status}")
                    await self.client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run.id)
            return True
        except Exception as e:
            logging.error(f"Failed to cancel run for thread {thread_id}: {e}")
            return False

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
                           tool_choice: Optional[Any] = None,
                           tools: Optional[List[Any]] = None,
                           ) -> (Optional[str], Optional[Any]):
            if tools is None:
                # デフォルトのツール（関数）の定義
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
            
            run_params = {
                "thread_id": assistant.thread_id,
                "assistant_id": assistant.assistant_id,
                "tools": tools,
                "truncation_strategy": {
                    "type": "auto",
                    "last_messages": None,
                },
            }
            if tool_choice:
                run_params["tool_choice"] = tool_choice

            run = await self.client.beta.threads.runs.create_and_poll(**run_params)

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
                    # 呼び出し元にtool_callを返して判断を仰ぐ
                    return None, tool_calls[0]
                else:
                    return "FAILED: Tool call required but no tool_calls found.", None

            else: # failed, cancelled, expired
                error_message = f"Run failed with status: {run.status}"
                if run.last_error:
                    error_message += f" - {run.last_error.message}"
                    logging.error(f"Run last_error: {run.last_error}")
                logging.error(error_message)
                logging.error(f"Run object: {run}")
                # FAILED: から始まる文字列を返す
                return f"FAILED: {error_message}", None
