import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from modelUserDef import UserDef, AssistantDef
from modelHistory import MessageInfo
from modelChat import ToolCallDetected, MessageForwarded, ConversationContinueAccepted
from modelRole import PatientRoleProvider
from openai_assistant import OpenAIAssistantWrapper
import json
from random import random
from hashlib import sha1


def get_id() -> str:
    """Generate a unique ID based on timestamp and random number"""
    base = f"{datetime.now().timestamp()}-{random()}"
    return sha1(base.encode()).hexdigest()


async def log_message(db, session_id: str, user_name: str, patient_id: str, user_role: str, sender: str, message: str, logger, is_initial_message: bool = False, ai_role: str = None):
    """Log a message to the database"""
    if not db:
        return
    try:
        # 動的インポートで循環インポートを回避
        import modelDatabase
        
        # JST (UTC+9) のタイムゾーンを定義
        jst = timezone(timedelta(hours=9))
        # ログメッセージが作成された正確な時刻を記録
        log_entry = modelDatabase.ChatLog(
            session_id=session_id, user_name=user_name, patient_id=patient_id,
            user_role=user_role, sender=sender, message=message,
            ai_role=ai_role, is_initial_message=is_initial_message,
            created_at=datetime.now(jst)
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        logger.debug(f"Logged message for session {session_id}")
    except Exception as e:
        logger.error(f"Failed to log message: {e}")
        db.rollback()


class AIConversationManager:
    """傍聴者セッション用のAI同士の自動対話管理"""
    
    def __init__(self, session, observer_user: UserDef, oaw: OpenAIAssistantWrapper, 
                 role_provider: PatientRoleProvider, db, logger):
        self.session = session
        self.observer_user = observer_user
        self.oaw = oaw
        self.role_provider = role_provider
        self.db = db
        self.logger = logger
        
        self.nurse_ai: Optional[AssistantDef] = None
        self.patient_ai: Optional[AssistantDef] = None
        self.is_running = False
        self.message_interval = 0.5  # 500ms
        self.conversation_task: Optional[asyncio.Task] = None
        self.current_turn = "patient"  # "nurse" or "patient" - 保健師AIが初期メッセージを送信するので患者AIから開始
        
    async def initialize_ais(self) -> bool:
        """保健師AIと患者AIを初期化"""
        try:
            # assistants.jsonから各AIのIDを取得
            with open("assistants.json", "r") as f:
                assistants = json.load(f)
            
            if len(assistants) < 2:
                self.logger.error("Insufficient assistant IDs in assistants.json")
                return False
                
            # 保健師AIを初期化
            self.nurse_ai = AssistantDef(
                user_id=get_id(),
                role="保健師",
                assistant_id=assistants[1],  # 2番目のAssistant ID（保健師用）
                thread_id=await self.oaw.create_thread()
            )
            
            # 患者AIを初期化
            self.patient_ai = AssistantDef(
                user_id=get_id(),
                role="患者",
                assistant_id=assistants[0],  # 1番目のAssistant ID（患者用）
                thread_id=await self.oaw.create_thread()
            )
            
            # セッションにAIを追加
            self.session.users.extend([self.nurse_ai, self.patient_ai])
            
            self.logger.info(f"Initialized AI conversation: nurse_ai={self.nurse_ai.user_id}, patient_ai={self.patient_ai.user_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize AIs: {e}")
            return False
    
    async def setup_ai_prompts(self, interview_date_str: str = None) -> bool:
        """AIにプロンプトを設定"""
        try:
            patient_id = self.observer_user.target_patient_id or "1"
            
            # 面接日が渡されていない場合は患者プロンプトから取得
            if not interview_date_str:
                _, interview_date_str = self.role_provider.get_patient_prompt_chunks(patient_id)
            
            # 患者AIのプロンプト設定（計算した面接日を使用）
            prompt_chunks, _ = self.role_provider.get_patient_prompt_chunks(patient_id, interview_date_str)
            for chunk in prompt_chunks:
                await self.oaw.add_message_to_thread(self.patient_ai.thread_id, chunk)
                self.session.history.history.append(MessageInfo(role="system", text=chunk))
                await log_message(self.db, self.session.session_id, "System", patient_id, "患者", "System", chunk, self.logger)
            
            # 患者AIの初期メッセージを先に追加（正しい順序）
            patient_details = self.role_provider.get_patient_details(patient_id)
            patient_name = patient_details.get("name", "名無し")
            initial_patient_message = f"私の名前は{patient_name}です。何でも聞いてください。"
            
            # 初期メッセージをセッション履歴に追加
            self.session.history.history.append(MessageInfo(role="患者", text=initial_patient_message))
            await log_message(self.db, self.session.session_id, "AI", patient_id, "傍聴者", "Assistant", initial_patient_message, self.logger, is_initial_message=True, ai_role="患者")
            
            # 保健師AIのプロンプト設定
            interviewer_chunks, initial_nurse_message = self.role_provider.get_interviewer_prompt_chunks()
            for chunk in interviewer_chunks:
                await self.oaw.add_message_to_thread(self.nurse_ai.thread_id, chunk)
                self.session.history.history.append(MessageInfo(role="system", text=chunk))
                await log_message(self.db, self.session.session_id, "System", "N/A", "保健師", "System", chunk, self.logger)
            
            # 保健師AIの初期メッセージを会話ログに含める
            self.session.history.history.append(MessageInfo(role="保健師", text=initial_nurse_message))
            await log_message(self.db, self.session.session_id, "AI", self.nurse_ai.assistant_id, "傍聴者", "Assistant", initial_nurse_message, self.logger, is_initial_message=False, ai_role="保健師")
            
            self.logger.info(f"AI prompts setup completed for session {self.session.session_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup AI prompts: {e}")
            return False
    
    async def start_conversation(self):
        """AI同士の対話を開始"""
        if self.is_running:
            self.logger.warning("Conversation is already running")
            return
            
        self.is_running = True
        self.logger.info(f"Starting AI conversation for session {self.session.session_id}")
        
        # 対話タスクを開始
        self.conversation_task = asyncio.create_task(self._conversation_loop())
    
    async def _conversation_loop(self):
        """対話のメインループ"""
        try:
            # 保健師AIの初期メッセージを送信（患者AIの初期メッセージはフロントに送信しない）
            initial_nurse_message = None
            for msg in self.session.history.history:
                if msg.role == "保健師":
                    initial_nurse_message = msg.text
                    break
            
            if initial_nurse_message:
                # 傍聴者に保健師AIの初期メッセージを送信
                message_data = {
                    "msg_type": "MessageForwarded",
                    "session_id": self.session.session_id,
                    "user_msg": initial_nurse_message,
                    "ai_role": "保健師"
                }
                await self.observer_user.ws.send_json(message_data)
                
                # 少し待ってから対話開始
                await asyncio.sleep(self.message_interval)
            
            while self.is_running:
                # 停止シグナルを再チェック
                if not self.is_running:
                    break
                    
                # 現在の話者を決定
                current_ai = self.nurse_ai if self.current_turn == "nurse" else self.patient_ai
                
                # 最後のメッセージを取得（相手からのメッセージ）
                last_message = None
                if self.session.history.history:
                    for msg in reversed(self.session.history.history):
                        if msg.role in ["保健師", "患者"] and msg.role != current_ai.role:
                            last_message = msg.text
                            break
                
                # 最初のターンでは保健師AIの初期メッセージが既に存在するので、患者AIが応答する
                if last_message or (self.current_turn == "patient" and len([msg for msg in self.session.history.history if msg.role == "保健師"]) > 0):
                    # 停止シグナルを再チェック
                    if not self.is_running:
                        break
                        
                    # AIにメッセージを送信
                    # 患者AIの場合、最初のターンでは保健師AIの初期メッセージを取得
                    if self.current_turn == "patient" and not last_message:
                        for msg in self.session.history.history:
                            if msg.role == "保健師":
                                last_message = msg.text
                                break
                    
                    if last_message and self.is_running:
                        response_msg, tool_call = await self.oaw.send_message(
                            current_ai, 
                            last_message,
                            tools=[] if current_ai.role == "患者" else None  # 患者AIはFunction Calling無効
                        )
                    
                        if tool_call and tool_call.function.name == "end_conversation_and_start_debriefing":
                            # 対話終了の確認ダイアログを送信
                            await self.observer_user.ws.send_json(ToolCallDetected(
                                session_id=self.session.session_id
                            ).dict())
                            break
                        elif response_msg and not response_msg.startswith("FAILED:"):
                            # 停止シグナルを再チェック
                            if not self.is_running:
                                break
                                
                            # Function call関連のテキストを除去
                            cleaned_msg = self._clean_function_call_text(response_msg)
                            
                            # end_conversation_and_start_debriefingが含まれる場合はメッセージを送信しない
                            if "end_conversation_and_start_debriefing" in response_msg.lower():
                                # ツールコール検出処理
                                await self.observer_user.ws.send_json(ToolCallDetected(
                                    session_id=self.session.session_id
                                ).dict())
                                break
                            
                            # 空のメッセージや意味のないメッセージは送信しない
                            if not cleaned_msg or len(cleaned_msg.strip()) < 3:
                                continue
                            
                            # 停止シグナルを最終チェック
                            if not self.is_running:
                                break
                            
                            # メッセージをセッション履歴に追加
                            self.session.history.history.append(MessageInfo(role=current_ai.role, text=cleaned_msg))
                            await log_message(
                                self.db, self.session.session_id, "AI", current_ai.assistant_id, 
                                "傍聴者", "Assistant", cleaned_msg, self.logger, ai_role=current_ai.role
                            )
                            
                            # 傍聴者に転送（どのAIの発言かを示すカスタムメッセージ）
                            if self.is_running:  # 停止チェック後にメッセージ送信
                                message_data = {
                                    "msg_type": "MessageForwarded",
                                    "session_id": self.session.session_id,
                                    "user_msg": cleaned_msg,
                                    "ai_role": current_ai.role  # 発言者のロール情報を追加
                                }
                                await self.observer_user.ws.send_json(message_data)
                            
                            # 話者を切り替え
                            self.current_turn = "patient" if self.current_turn == "nurse" else "nurse"
                
                # 次のメッセージまで待機
                await asyncio.sleep(self.message_interval)
                
        except asyncio.CancelledError:
            self.logger.info("Conversation loop was cancelled")
        except Exception as e:
            self.logger.error(f"Error in conversation loop: {e}")
        finally:
            self.is_running = False
    
    async def stop_conversation(self):
        """対話を中断"""
        if not self.is_running:
            return
            
        self.logger.info(f"Stopping AI conversation for session {self.session.session_id}")
        self.is_running = False
        
        if self.conversation_task:
            self.conversation_task.cancel()
            try:
                await asyncio.wait_for(self.conversation_task, timeout=2.0)
            except asyncio.CancelledError:
                self.logger.info(f"AI conversation task cancelled for session {self.session.session_id}")
            except asyncio.TimeoutError:
                self.logger.warning(f"AI conversation task cancellation timed out for session {self.session.session_id}")
            except Exception as e:
                self.logger.error(f"Error while stopping AI conversation: {e}")
        
        # 進行中のOpenAI APIリクエストもキャンセル
        try:
            if self.nurse_ai and self.nurse_ai.thread_id:
                await self.oaw.cancel_run(self.nurse_ai.thread_id)
            if self.patient_ai and self.patient_ai.thread_id:
                await self.oaw.cancel_run(self.patient_ai.thread_id)
        except Exception as e:
            self.logger.warning(f"Error cancelling OpenAI runs: {e}")
        
        self.logger.info(f"AI conversation stopped for session {self.session.session_id}")
    
    async def handle_continue_conversation(self):
        """対話続行要求への対応"""
        if not self.is_running:
            # 対話を再開
            await self.start_conversation()
            
        # 確認メッセージを送信
        await self.observer_user.ws.send_json(ConversationContinueAccepted(
            session_id=self.session.session_id
        ).dict())
    
    async def cleanup(self):
        """リソース解放"""
        await self.stop_conversation()
        
        # スレッドを削除
        if self.nurse_ai and self.nurse_ai.thread_id:
            try:
                await self.oaw.delete_thread(self.nurse_ai)
            except Exception as e:
                self.logger.warning(f"Failed to delete nurse AI thread: {e}")
                
        if self.patient_ai and self.patient_ai.thread_id:
            try:
                await self.oaw.delete_thread(self.patient_ai)
            except Exception as e:
                self.logger.warning(f"Failed to delete patient AI thread: {e}")
        
        self.logger.info(f"AI conversation manager cleaned up for session {self.session.session_id}")
    
    def _clean_function_call_text(self, message: str) -> str:
        """Function call関連のテキストを除去"""
        import re
        
        # まず、end_conversation_and_start_debriefingが含まれる場合は空文字列を返す
        if "end_conversation_and_start_debriefing" in message.lower():
            return ""
        
        # Function call関連のパターンを削除
        patterns = [
            r'end_conversation_and_start_debriefing',
            r'submit_debriefing_report',
            r'Tool\s*call\s*detected',
            r'Function\s*call',
            r'\bfunction\s*:\s*\w+',
            r'\btools?\s*=\s*\[?\]?',
            r'\btool_choice\s*=',
            r'\bassistant_id\s*=',
            r'\bthread_id\s*=',
            r'\buser_msg\s*=',
            r'\bai_role\s*=',
            r'^.*end_conversation_and_start_debriefing.*$',
            r'.*function.*call.*',
            r'.*tool.*call.*',
            r'.*debriefing.*',
            r'.*evaluation.*'
        ]
        
        cleaned_message = message
        for pattern in patterns:
            cleaned_message = re.sub(pattern, '', cleaned_message, flags=re.IGNORECASE | re.MULTILINE)
        
        # 複数の空白や改行を整理
        cleaned_message = re.sub(r'\s+', ' ', cleaned_message).strip()
        
        # 句読点だけが残った場合も空文字列とする
        if cleaned_message in ['。', '、', '.', ',', '!', '?', '！', '？']:
            return ""
            
        return cleaned_message
