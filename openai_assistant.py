import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pydantic import BaseModel
from modelUserDef import AssistantDef
from openai import AsyncOpenAI, RateLimitError, APIStatusError, APIConnectionError, APITimeoutError
from openai_etc import openai_get_apikey
from typing import Optional, Any, List, Dict
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


@dataclass
class ConversationState:
    """Responses API 会話状態管理"""
    pending_messages: List[dict] = field(default_factory=list)
    last_response_id: Optional[str] = None
    unresolved_call_id: Optional[str] = None  # 未解決の function_call の call_id


class OpenAIAssistantWrapper():
    def __init__(self, config):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=openai_get_apikey(config.apikey_storage)
        )
        self.rate_limit_info = RateLimitInfo()
        self._conversations: Dict[str, ConversationState] = {}
        self._assistant_cache: Dict[str, dict] = {}  # assistant_id -> {model, instructions}

    async def create_thread(self):
        """会話コンテキストを作成（ローカル ID を返す）"""
        conv_id = str(uuid.uuid4())
        self._conversations[conv_id] = ConversationState()
        return conv_id

    async def get_assistant_info(self, assistant_id: str):
        """
        指定されたAssistant IDの情報を取得する
        （Assistants API は廃止期間中も利用可能）
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

    async def _get_cached_assistant_info(self, assistant_id: str) -> dict:
        """assistant_id のキャッシュを取得（なければ API で取得してキャッシュ）"""
        if assistant_id not in self._assistant_cache:
            info = await self.get_assistant_info(assistant_id)
            if info:
                self._assistant_cache[assistant_id] = info
            else:
                # フォールバック: 最低限のデフォルト
                self._assistant_cache[assistant_id] = {
                    "model": "gpt-4.1",
                    "instructions": None,
                }
        return self._assistant_cache[assistant_id]

    async def delete_thread(self, assistant: AssistantDef):
        """会話状態を削除"""
        self._conversations.pop(assistant.thread_id, None)
        return True

    async def delete_thread_by_id(self, thread_id: str):
        """thread_idから会話状態を削除"""
        if not thread_id:
            return None
        self._conversations.pop(thread_id, None)
        return True

    async def cancel_run(self, thread_id: str):
        """Responses API は同期的なためキャンセル不要（no-op）"""
        return True

    async def add_message_to_thread(self, conv_id: str, message_text: str):
        """
        会話コンテキストにメッセージを追加する。
        これはAIへの初期指示（ペルソナ設定）を注入するために使用する。
        """
        conv = self._conversations.get(conv_id)
        if conv is not None:
            conv.pending_messages.append({"role": "user", "content": message_text})
        else:
            logging.warning(f"Conversation {conv_id} not found, cannot add message")

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
        # 日本語文字の割合を概算
        japanese_chars = sum(1 for char in text if ord(char) > 127)
        english_chars = len(text) - japanese_chars

        # トークン数推定
        estimated_tokens = (japanese_chars / 1.5) + (english_chars / 4)

        # 余裕を持って1.2倍にする
        return int(estimated_tokens * 1.2)

    async def _check_and_wait_for_rate_limits(self, estimated_tokens: int = 1000, user_ws=None, session_id=None, user_role=None):
        """レートリミットをチェックして必要に応じて待機"""
        try:
            # リクエスト数制限チェック
            should_wait_requests, wait_time_requests = self.rate_limit_info.should_wait_for_requests()
            if should_wait_requests and wait_time_requests > 0:
                logging.info(f"Rate limit proactive wait for requests: {wait_time_requests:.1f} seconds")

                # 傍聴者ロールの場合のみWebSocketで通知（最低2秒以上の待機時間がある場合のみ）
                if user_role == "傍聴者" and user_ws and session_id and wait_time_requests >= 2.0:
                    await self._send_rate_limit_notification(user_ws, session_id, max(2, int(wait_time_requests)), "リクエスト制限")

                await sleep(wait_time_requests)

            # トークン数制限チェック
            should_wait_tokens, wait_time_tokens = self.rate_limit_info.should_wait_for_tokens(estimated_tokens)
            if should_wait_tokens and wait_time_tokens > 0:
                logging.info(f"Rate limit proactive wait for tokens: {wait_time_tokens:.1f} seconds")

                # 傍聴者ロールの場合のみWebSocketで通知（最低2秒以上の待機時間がある場合のみ）
                if user_role == "傍聴者" and user_ws and session_id and wait_time_tokens >= 2.0:
                    await self._send_rate_limit_notification(user_ws, session_id, max(2, int(wait_time_tokens)), "トークン制限")

                await sleep(wait_time_tokens)

        except Exception as e:
            logging.warning(f"Error in rate limit checking: {e}")

    async def _send_rate_limit_notification(self, user_ws, session_id: str, wait_seconds: int, reason: str):
        """レート制限待機通知をWebSocketで送信"""
        try:
            if not user_ws:
                return

            from modelChat import RateLimitWaitNotification
            notification = RateLimitWaitNotification(
                session_id=session_id,
                wait_seconds=wait_seconds,
                message=f"APIの{reason}により{wait_seconds}秒間待機します..."
            )

            # WebSocket接続状態を確認
            if hasattr(user_ws, 'client_state') and user_ws.client_state.name != 'CONNECTED':
                logging.warning(f"WebSocket not connected, skipping rate limit notification")
                return

            await user_ws.send_json(notification.dict())
            logging.debug(f"Rate limit notification sent: {wait_seconds}s for {reason}")
        except Exception as e:
            logging.warning(f"Failed to send rate limit notification: {e}")

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
                           user_ws=None,
                           session_id: Optional[str] = None,
                           user_role: Optional[str] = None,
                           model: Optional[str] = None,
                           instructions: Optional[str] = None,
                           ) -> (Optional[str], Optional[Any]):
            if tools is None:
                tools = []

            # 初回実行時に保守的な制限値を設定
            if self.rate_limit_info.limit_requests == 0:
                self._initialize_conservative_limits()

            # トークン数を推定してレートリミット事前チェック
            estimated_tokens = self._estimate_tokens(request_text)
            await self._check_and_wait_for_rate_limits(estimated_tokens, user_ws, session_id, user_role)

            # 会話状態を取得
            conv = self._conversations.get(assistant.thread_id)
            if conv is None:
                # 会話状態がない場合は新規作成
                conv = ConversationState()
                self._conversations[assistant.thread_id] = conv

            # instructions を決定: 明示的引数 > キャッシュ > None
            actual_instructions = instructions
            if actual_instructions is None:
                cached = await self._get_cached_assistant_info(assistant.assistant_id)
                actual_instructions = cached.get("instructions")

            # model を決定: 明示的引数 > キャッシュ
            actual_model = model
            if actual_model is None:
                cached = await self._get_cached_assistant_info(assistant.assistant_id)
                actual_model = cached.get("model", "gpt-4.1")

            # input を構築
            input_messages = []

            # 前回のレスポンスに未解決の function_call がある場合、
            # function_call_output を先頭に追加して解決する
            if conv.unresolved_call_id and conv.last_response_id:
                input_messages.append({
                    "type": "function_call_output",
                    "call_id": conv.unresolved_call_id,
                    "output": "{}"
                })
                conv.unresolved_call_id = None

            # pending_messages + 新メッセージ
            input_messages.extend(conv.pending_messages)
            input_messages.append({"role": "user", "content": request_text})

            # API パラメータ構築
            api_params = {
                "model": actual_model,
                "input": input_messages,
                "tools": tools,
                "store": True,
                "truncation": "auto",
            }
            if actual_instructions:
                api_params["instructions"] = actual_instructions
            if tool_choice:
                api_params["tool_choice"] = tool_choice
            if conv.last_response_id:
                api_params["previous_response_id"] = conv.last_response_id

            # レート制限エラーに対するリトライ機能
            for attempt in range(max_retries + 1):
                try:
                    response = await self.client.responses.create(**api_params)

                    # 会話状態を更新
                    conv.last_response_id = response.id
                    conv.pending_messages = []

                    # API使用量を追跡
                    if response.usage:
                        self._update_rate_limit_estimation(
                            response.usage.total_tokens,
                            response.usage.input_tokens,
                            response.usage.output_tokens
                        )

                    # レスポンス解析: function_call を探す
                    for item in response.output:
                        if item.type == "function_call":
                            # 未解決の function_call として記録
                            # （次回の send_message 時に function_call_output で解決する）
                            conv.unresolved_call_id = item.call_id
                            return None, item

                    # テキストレスポンスの場合は unresolved をクリア
                    conv.unresolved_call_id = None

                    # テキストレスポンスを返す
                    text = response.output_text
                    if text:
                        return text, None
                    else:
                        return "FAILED: No response from assistant.", None

                except RateLimitError as e:
                    if attempt < max_retries:
                        retry_delay = self._extract_retry_delay(str(e))
                        logging.warning(
                            f"Rate limit exceeded (attempt {attempt + 1}/{max_retries + 1}). "
                            f"Retrying in {retry_delay} seconds..."
                        )
                        await sleep(retry_delay)
                        continue
                    else:
                        error_message = f"Rate limit exceeded after {max_retries + 1} attempts: {e}"
                        logging.error(error_message)
                        return f"FAILED: {error_message}", None

                except (APIStatusError, APIConnectionError, APITimeoutError) as e:
                    if attempt < max_retries:
                        retry_delay = 2.0 * (2 ** attempt)  # 2秒 → 4秒 → 8秒
                        logging.warning(
                            f"OpenAI API error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {retry_delay} seconds..."
                        )
                        await sleep(retry_delay)
                        continue
                    else:
                        error_message = f"API error after {max_retries + 1} attempts: {e}"
                        logging.error(error_message)
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
