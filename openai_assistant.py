import logging
import re
import time
from dataclasses import dataclass
from pydantic import BaseModel
from modelUserDef import AssistantDef
from openai import AsyncOpenAI
from openai_etc import openai_get_apikey
from typing import Optional, Any, List
from asyncio import sleep as sleep

@dataclass
class RateLimitInfo:
    """レートリミット情報を管理するクラス"""
    limit_requests: int = 0
    limit_tokens: int = 0
    remaining_requests: int = 0
    remaining_tokens: int = 0
    reset_requests_time: float = 0.0  # Unix timestamp
    reset_tokens_time: float = 0.0    # Unix timestamp
    last_updated: float = 0.0         # Unix timestamp
    
    def parse_reset_time(self, reset_str: str) -> float:
        """リセット時間文字列（例: "1s", "6m0s"）をUnixタイムスタンプに変換"""
        try:
            current_time = time.time()
            
            # "1s", "6m0s", "1h30m0s" などの形式を解析
            total_seconds = 0
            
            # 時間の抽出 (h)
            h_match = re.search(r'(\d+)h', reset_str)
            if h_match:
                total_seconds += int(h_match.group(1)) * 3600
            
            # 分の抽出 (m)
            m_match = re.search(r'(\d+)m', reset_str)
            if m_match:
                total_seconds += int(m_match.group(1)) * 60
            
            # 秒の抽出 (s)
            s_match = re.search(r'(\d+)s', reset_str)
            if s_match:
                total_seconds += int(s_match.group(1))
            
            return current_time + total_seconds
        except Exception as e:
            logging.warning(f"Failed to parse reset time '{reset_str}': {e}")
            return time.time() + 60  # 1分後をデフォルト
    
    def update_from_headers(self, headers: dict):
        """HTTPヘッダーからレートリミット情報を更新"""
        try:
            if 'x-ratelimit-limit-requests' in headers:
                self.limit_requests = int(headers['x-ratelimit-limit-requests'])
            if 'x-ratelimit-limit-tokens' in headers:
                self.limit_tokens = int(headers['x-ratelimit-limit-tokens'])
            if 'x-ratelimit-remaining-requests' in headers:
                self.remaining_requests = int(headers['x-ratelimit-remaining-requests'])
            if 'x-ratelimit-remaining-tokens' in headers:
                self.remaining_tokens = int(headers['x-ratelimit-remaining-tokens'])
            if 'x-ratelimit-reset-requests' in headers:
                self.reset_requests_time = self.parse_reset_time(headers['x-ratelimit-reset-requests'])
            if 'x-ratelimit-reset-tokens' in headers:
                self.reset_tokens_time = self.parse_reset_time(headers['x-ratelimit-reset-tokens'])
            
            self.last_updated = time.time()
            
            logging.debug(f"Rate limit updated: Requests {self.remaining_requests}/{self.limit_requests}, "
                         f"Tokens {self.remaining_tokens}/{self.limit_tokens}")
        except Exception as e:
            logging.warning(f"Failed to update rate limit from headers: {e}")
    
    def should_wait_for_requests(self, buffer_requests: int = 5) -> tuple[bool, float]:
        """リクエスト数制限に基づいて待機が必要かチェック"""
        current_time = time.time()
        
        # 古い情報の場合は制御しない
        if current_time - self.last_updated > 60:
            return False, 0.0
        
        # 残りリクエスト数がバッファ以下の場合は待機
        if self.remaining_requests <= buffer_requests:
            wait_time = max(0, self.reset_requests_time - current_time)
            return True, wait_time
        
        return False, 0.0
    
    def should_wait_for_tokens(self, estimated_tokens: int, buffer_tokens: int = 5000) -> tuple[bool, float]:
        """トークン数制限に基づいて待機が必要かチェック"""
        current_time = time.time()
        
        # 古い情報の場合は制御しない
        if current_time - self.last_updated > 60:
            return False, 0.0
        
        # 残りトークン数が推定使用量+バッファ以下の場合は待機
        if self.remaining_tokens <= (estimated_tokens + buffer_tokens):
            wait_time = max(0, self.reset_tokens_time - current_time)
            return True, wait_time
        
        return False, 0.0

class OpenAIAssistantWrapper():
    def __init__(self, config):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=openai_get_apikey(config.apikey_storage)
        )
        self.rate_limit_info = RateLimitInfo()

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

    def _estimate_tokens(self, text: str) -> int:
        """テキストのトークン数を概算する（簡易版）"""
        # 簡易的な推定: 英語の場合は約4文字で1トークン、日本語の場合は約1.5文字で1トークン
        # より正確な推定には tiktoken ライブラリを使用できますが、ここでは簡易版を使用
        
        # 日本語文字の割合を概算
        japanese_chars = sum(1 for char in text if ord(char) > 127)
        english_chars = len(text) - japanese_chars
        
        # トークン数推定
        estimated_tokens = (japanese_chars / 1.5) + (english_chars / 4)
        
        # 余裕を持って1.2倍にする
        return int(estimated_tokens * 1.2)

    async def _check_and_wait_for_rate_limits(self, estimated_tokens: int = 1000):
        """レートリミットをチェックして必要に応じて待機"""
        try:
            # リクエスト数制限チェック
            should_wait_requests, wait_time_requests = self.rate_limit_info.should_wait_for_requests()
            if should_wait_requests and wait_time_requests > 0:
                logging.info(f"Rate limit proactive wait for requests: {wait_time_requests:.1f} seconds")
                await sleep(wait_time_requests)
            
            # トークン数制限チェック
            should_wait_tokens, wait_time_tokens = self.rate_limit_info.should_wait_for_tokens(estimated_tokens)
            if should_wait_tokens and wait_time_tokens > 0:
                logging.info(f"Rate limit proactive wait for tokens: {wait_time_tokens:.1f} seconds")
                await sleep(wait_time_tokens)
                
        except Exception as e:
            logging.warning(f"Error in rate limit checking: {e}")

    def _update_rate_limit_estimation(self, total_tokens: int, prompt_tokens: int, completion_tokens: int):
        """API使用量に基づいてレートリミット推定を更新"""
        try:
            current_time = time.time()
            
            # 使用量を追跡（簡易版）
            if self.rate_limit_info.limit_tokens > 0:
                # 残りトークン数を減算（推定）
                self.rate_limit_info.remaining_tokens = max(0, self.rate_limit_info.remaining_tokens - total_tokens)
                
            if self.rate_limit_info.limit_requests > 0:
                # 残りリクエスト数を減算
                self.rate_limit_info.remaining_requests = max(0, self.rate_limit_info.remaining_requests - 1)
            
            # 推定情報を更新
            self.rate_limit_info.last_updated = current_time
            
            logging.debug(f"Updated rate limit estimation: "
                         f"Requests: {self.rate_limit_info.remaining_requests}/{self.rate_limit_info.limit_requests}, "
                         f"Tokens: {self.rate_limit_info.remaining_tokens}/{self.rate_limit_info.limit_tokens}")
                         
        except Exception as e:
            logging.warning(f"Error updating rate limit estimation: {e}")

    def _initialize_conservative_limits(self):
        """保守的なレートリミット初期値を設定"""
        if self.rate_limit_info.limit_requests == 0:
            # OpenAI GPT-4の一般的な制限値（保守的）
            self.rate_limit_info.limit_requests = 60  # RPM
            self.rate_limit_info.remaining_requests = 50
            
        if self.rate_limit_info.limit_tokens == 0:
            self.rate_limit_info.limit_tokens = 30000  # TPM
            self.rate_limit_info.remaining_tokens = 25000
            
        # リセット時間を1分後に設定
        current_time = time.time()
        self.rate_limit_info.reset_requests_time = current_time + 60
        self.rate_limit_info.reset_tokens_time = current_time + 60
        self.rate_limit_info.last_updated = current_time

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

            # 初回実行時に保守的な制限値を設定
            if self.rate_limit_info.limit_requests == 0:
                self._initialize_conservative_limits()
            
            # トークン数を推定してレートリミット事前チェック
            estimated_tokens = self._estimate_tokens(request_text)
            await self._check_and_wait_for_rate_limits(estimated_tokens)

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
                    
                    # API使用量を追跡（概算）
                    if run.usage:
                        # 実際の使用量が取得できた場合は、レートリミット情報を更新
                        self._update_rate_limit_estimation(
                            run.usage.total_tokens,
                            run.usage.prompt_tokens,
                            run.usage.completion_tokens
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
                            # 呼び出し元にtool_callを返して判断を仰ぐ
                            return None, tool_calls[0]
                        else:
                            return "FAILED: Tool call required but no tool_calls found.", None

                    elif run.status == 'failed' and run.last_error:
                        # リトライ対象のエラーかどうかチェック
                        retryable_errors = [
                            'rate_limit_exceeded',    # レート制限エラー
                            'server_error',           # OpenAIサーバーエラー  
                            'timeout',                # タイムアウトエラー
                            'internal_error',         # 内部エラー
                            'service_unavailable',    # サービス利用不可
                            'bad_gateway',            # バッドゲートウェイ
                            'api_error'               # 一般的なAPIエラー
                        ]
                        if run.last_error.code in retryable_errors and attempt < max_retries:
                            if run.last_error.code == 'rate_limit_exceeded':
                                # レート制限エラー: APIが指定した待機時間を使用
                                retry_delay = self._extract_retry_delay(run.last_error.message)
                                logging.warning(
                                    f"Rate limit exceeded (attempt {attempt + 1}/{max_retries + 1}). "
                                    f"Retrying in {retry_delay} seconds..."
                                )
                            else:
                                # その他のリトライ可能エラー: 指数バックオフを使用
                                retry_delay = 2.0 * (2 ** attempt)  # 2秒 → 4秒 → 8秒
                                logging.warning(
                                    f"OpenAI API error ({run.last_error.code}): {run.last_error.message} "
                                    f"(attempt {attempt + 1}/{max_retries + 1}). Retrying in {retry_delay} seconds..."
                                )
                            
                            await sleep(retry_delay)
                            continue
                        else:
                            # 最大リトライ回数に達した場合またはリトライ対象外エラー
                            error_message = f"Run failed after {max_retries + 1} attempts: {run.last_error.code} - {run.last_error.message}"
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
