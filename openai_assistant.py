import logging
import re
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

    def _extract_retry_delay(self, error_message: str) -> float:
        """エラーメッセージから待機時間を抽出"""
        try:
            # "Please try again in X.Xs." の部分を抽出
            match = re.search(r'Please try again in ([\d.]+)s\.', error_message)
            if match:
                return float(match.group(1))
        except Exception as e:
            logging.warning(f"Failed to extract retry delay: {e}")
        return 30.0  # デフォルト待機時間

    async def send_message(self,
                           assistant: AssistantDef,
                           request_text: str,
                           tool_choice: Optional[Any] = None,
                           tools: Optional[List[Any]] = None,
                           max_retries: int = 3,
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

            # レート制限エラーに対するリトライ機能
            for attempt in range(max_retries + 1):
                try:
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

                    elif run.status == 'failed' and run.last_error and run.last_error.code == 'rate_limit_exceeded':
                        # レート制限エラーの場合はリトライ
                        if attempt < max_retries:
                            retry_delay = self._extract_retry_delay(run.last_error.message)
                            logging.warning(
                                f"Rate limit exceeded (attempt {attempt + 1}/{max_retries + 1}). "
                                f"Retrying in {retry_delay} seconds..."
                            )
                            await sleep(retry_delay)
                            continue
                        else:
                            # 最大リトライ回数に達した場合
                            error_message = f"Rate limit exceeded after {max_retries + 1} attempts: {run.last_error.message}"
                            logging.error(error_message)
                            return f"FAILED: {error_message}", None

                    else: # その他のfailed, cancelled, expired
                        error_message = f"Run failed with status: {run.status}"
                        if run.last_error:
                            error_message += f" - {run.last_error.message}"
                            logging.error(f"Run last_error: {run.last_error}")
                        logging.error(error_message)
                        logging.error(f"Run object: {run}")
                        return f"FAILED: {error_message}", None

                except Exception as e:
                    # その他の例外（接続エラーなど）
                    if attempt < max_retries:
                        wait_time = 5.0 * (2 ** attempt)  # 指数バックオフ
                        logging.warning(f"OpenAI API error (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {wait_time} seconds...")
                        await sleep(wait_time)
                        continue
                    else:
                        logging.error(f"OpenAI API failed after {max_retries + 1} attempts: {e}")
                        return f"FAILED: API error after {max_retries + 1} attempts: {e}", None

            # ここには到達しないはずだが、安全のため
            return "FAILED: Unexpected error in retry loop", None
