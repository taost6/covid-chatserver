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

    async def delete_thread(self, assistant: AssistantDef):
        status = await self.client.beta.threads.delete(assistant.thread_id)
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
                    # tool_choiceが設定されている場合、tool_callをそのまま返す
                    if tool_choice:
                        return None, tool_calls[0]

                    # tool_choiceがない場合（通常の会話終了検知）
                    tool_outputs = []
                    for tool_call in tool_calls:
                        # 各ツールコールに対して、空の成功を示す出力を生成
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": "{\"success\": true}", # JSON形式の文字列として成功レスポンス
                        })
                    
                    # ツール実行結果を送信してRunを継続
                    run_after_submit = await self.client.beta.threads.runs.submit_tool_outputs_and_poll(
                        thread_id=assistant.thread_id,
                        run_id=run.id,
                        tool_outputs=tool_outputs
                    )

                    # 再帰的にこの関数を呼ぶのではなく、完了後のメッセージを取得する
                    if run_after_submit.status == 'completed':
                        messages = await self.client.beta.threads.messages.list(
                            thread_id=assistant.thread_id,
                            order="desc",
                            limit=1
                        )
                        if messages.data and messages.data[0].role == "assistant":
                            assistant_response = messages.data[0].content[0].text.value
                            return assistant_response, tool_calls[0] # レスポンスとtool_callを両方返す
                        else:
                            return "FAILED: No response from assistant after tool call.", None
                    else:
                         # tool_callオブジェクトを返す
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
