from fastapi import FastAPI, Body, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict
from typing import List, Union, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import uuid
import os
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from random import random, choice
from hashlib import sha1

from modelChat import *
from modelUserDef import *
from modelHistory import *
from modelRole import PatientRoleProvider
import modelDatabase
from modelSession import Session as SessionModel # New
from modelPrompt import PromptTemplate, PromptTemplateService, initialize_default_prompts
from modelIRT import IRTItemType, IRTItemTypeService, IRTPatientInstance, IRTPatientInstanceService, IRTResponseJudgment, IRTResponseJudgmentService
from modelDatabase import db_retry
from openai import NotFoundError
from openai_assistant import OpenAIAssistantWrapper
from ai_conversation_manager import AIConversationManager, get_id as ai_get_id
from irt_batch_runner import IRTBatchRunner

# Logger setup
logger = logging.getLogger(__name__)

class ConversationEndDetector:
    """会話終了検出専用Assistantの管理クラス"""
    
    def __init__(self, oaw: OpenAIAssistantWrapper):
        self.oaw = oaw
        self.assistant_id = None
        self.thread_id = None
        self.assistant_def = None
        self._detection_lock = asyncio.Semaphore(1)  # 同時実行制御
        
    async def initialize(self):
        """会話終了検出用Assistantを初期化"""
        try:
            self.assistant_id = _get_conversation_end_detector_assistant_id()
            logger.debug(f"Retrieved conversation end detector assistant ID: {self.assistant_id}")
            
            self.thread_id = await self.oaw.create_thread()
            logger.debug(f"Created thread for conversation end detector: {self.thread_id}")
            
            # AssistantDefオブジェクトを作成
            self.assistant_def = AssistantDef(
                user_id=ai_get_id(),
                role="評価者",  # 会話終了検出専用だが、既存のrole制限に合わせる
                assistant_id=self.assistant_id,
                thread_id=self.thread_id
            )
            
            # 初期プロンプトを設定
            initial_prompt = (
                "あなたは会話終了検出の専門家です。"
                "一方が会話の終了を強く示唆する発言をし、その相手方がそれに合意して会話が終了したと判断される場合は、"
                "`detect_conversation_end`ツールを呼び出してください。"
                "会話が継続中の場合は何も応答せず、ツールも呼び出さないでください。"
            )
            
            await self.oaw.add_message_to_thread(self.thread_id, initial_prompt)
            logger.info(f"Conversation end detector initialized successfully: assistant_id={self.assistant_id}, thread_id={self.thread_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize conversation end detector: {e}")
            raise
    
    async def add_conversation_message(self, message_text: str, sender_role: str):
        """会話メッセージを検出用スレッドに追加（LLMの応答のみ）"""
        if not self.thread_id:
            logger.warning("Conversation end detector not initialized")
            return
            
        # LLMの応答のみを追加（患者AI、保健師AIの応答）
        if sender_role in ["患者", "保健師"]:
            try:
                # アクティブなrunがある場合は先にキャンセル
                await self.cancel_active_runs()
                
                formatted_message = f"[{sender_role}]: {message_text}"
                await self.oaw.add_message_to_thread(self.thread_id, formatted_message)
                logger.debug(f"Added message to end detector: [{sender_role}] {message_text[:50]}...")
            except Exception as e:
                logger.error(f"Failed to add message to conversation end detector: {e}")
                # メッセージ追加失敗時は検出をスキップ
    
    async def check_conversation_end(self):
        """会話終了検出を実行"""
        if not self.thread_id or not self.assistant_def:
            logger.warning("Conversation end detector not properly initialized")
            return None
        
        # セマフォを使用して同時実行を制御
        async with self._detection_lock:
            try:
                # 念のため再度アクティブなrunをチェック・キャンセル
                await self.cancel_active_runs()
                
                # 会話終了検出ツール定義
                detection_tool = {
                    "type": "function",
                    "name": "detect_conversation_end",
                    "description": "会話が自然に終了したと判断される場合に呼び出します",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "confidence": {
                                "type": "number",
                                "description": "会話終了の確信度（0.0-1.0）"
                            },
                            "reason": {
                                "type": "string",
                                "description": "終了判定の理由"
                            }
                        },
                        "required": ["confidence", "reason"]
                    }
                }
                
                # 検出指示を送信
                detection_instruction = "上記の会話を分析し、会話が終了したと判断される場合のみツールを呼び出してください。"
                
                response, tool_call = await self.oaw.send_message(
                    self.assistant_def,
                    detection_instruction,
                    tools=[detection_tool],
                    max_retries=1  # 高速化のためリトライ回数を削減
                )
                
                if tool_call and tool_call.name == "detect_conversation_end":
                    try:
                        args = json.loads(tool_call.arguments)
                        confidence = args.get("confidence", 0.0)
                        reason = args.get("reason", "")
                        
                        logger.info(f"Conversation end detected! Confidence: {confidence}, Reason: {reason}")
                        return {
                            "detected": True,
                            "confidence": confidence,
                            "reason": reason
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse end detection arguments: {e}")
                        return None
                
                return None  # 会話継続中
                
            except Exception as e:
                logger.error(f"Error during conversation end detection: {e}")
                return None
    
    async def reset(self):
        """検出器をリセット（新しいスレッドを作成）"""
        try:
            # 既存のスレッドを削除
            if self.thread_id and self.oaw:
                try:
                    await self.oaw.delete_thread_by_id(self.thread_id)
                    logger.debug("Old conversation end detector thread deleted")
                except Exception as e:
                    logger.warning(f"Failed to delete old end detector thread: {e}")
            
            # 新しいスレッドを作成
            self.thread_id = await self.oaw.create_thread()
            
            # AssistantDefオブジェクトを更新
            self.assistant_def = AssistantDef(
                user_id=ai_get_id(),
                role="評価者",  # 会話終了検出専用だが、既存のrole制限に合わせる
                assistant_id=self.assistant_id,
                thread_id=self.thread_id
            )
            
            # 初期プロンプトを設定
            initial_prompt = (
                "あなたは会話終了検出の専門家です。"
                "一方が会話の終了を強く示唆する発言をし、その相手方がそれに合意して会話が終了したと判断される場合は、"
                "`detect_conversation_end`ツールを呼び出してください。"
                "会話が継続中の場合は何も応答せず、ツールも呼び出さないでください。"
            )
            
            await self.oaw.add_message_to_thread(self.thread_id, initial_prompt)
            logger.info("Conversation end detector reset successfully")
            
        except Exception as e:
            logger.error(f"Failed to reset conversation end detector: {e}")
            raise
    
    async def cancel_active_runs(self):
        """アクティブなrunをキャンセル"""
        if self.thread_id and self.oaw:
            try:
                success = await self.oaw.cancel_run(self.thread_id)
                if success:
                    logger.info("Cancelled active runs for conversation end detector")
                else:
                    logger.debug("No active runs to cancel for conversation end detector")
            except Exception as e:
                logger.warning(f"Failed to cancel active runs for end detector: {e}")
    
    async def cleanup(self):
        """リソースをクリーンアップ"""
        if self.thread_id and self.oaw:
            try:
                await self.oaw.delete_thread_by_id(self.thread_id)
                logger.info("Conversation end detector thread cleaned up")
            except Exception as e:
                logger.warning(f"Failed to cleanup end detector thread: {e}")

class APISession(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    users: List[Union[UserDef, AssistantDef]]
    history: History
    session_id: str
    ai_conversation_manager: Optional[Any] = None
    conversation_end_detector: Optional[ConversationEndDetector] = None
    skip_next_end_detection: bool = False  # 次回の会話終了検知をスキップするフラグ

# --- Prompt Management Models ---
class PromptTemplateRequest(BaseModel):
    template_type: str
    prompt_text: str
    message_text: Optional[str] = None
    description: Optional[str] = None

class PromptTemplateResponse(BaseModel):
    id: int
    template_type: str
    version: int
    prompt_text: str
    message_text: Optional[str]
    description: Optional[str]
    is_active: bool
    created_at: datetime

# --- IRT Pydantic Models ---
class IRTItemTypeResponse(BaseModel):
    id: int
    catalog_version: int
    code: str
    category: str
    name_ja: str
    name_en: str
    description: Optional[str]
    investigation_phase: Optional[str]
    pdf_priority: Optional[str]
    investigation_direction: Optional[str]
    frequency: Optional[str]
    intensity: Optional[str]
    status: str
    created_at: datetime

class IRTPatientInstanceResponse(BaseModel):
    id: int
    catalog_version: int
    patient_id: str
    item_type_code: str
    instance_number: int
    date: Optional[str]
    description: Optional[str]
    investigation_direction_override: Optional[str]
    scene_category: Optional[str]
    density_closed: Optional[str]
    density_crowded: Optional[str]
    density_close_contact: Optional[str]
    related_patient_ids: Optional[str]
    is_detectable: bool
    notes: Optional[str]
    created_at: datetime

class IRTItemTypeBulkRequest(BaseModel):
    items: List[dict]

class IRTPatientInstanceBulkRequest(BaseModel):
    instances: List[dict]

class IRTResponseJudgmentResponse(BaseModel):
    id: int
    session_id: str
    instance_id: int
    is_correct: bool
    judgment_method: str
    confidence: Optional[float]
    evidence_message_ids: Optional[str]
    notes: Optional[str]
    judged_at: datetime

class PatientItemJudgmentDetail(BaseModel):
    session_id: str
    is_correct: bool
    confidence: Optional[float]
    notes: Optional[str]

class PatientItemStat(BaseModel):
    instance_id: int
    item_type_code: str
    instance_number: int
    description: Optional[str]
    is_detectable: bool
    total_judgments: int
    correct_count: int
    accuracy: float
    sessions: List[PatientItemJudgmentDetail]

class PatientSessionStat(BaseModel):
    session_id: str
    created_at: Optional[datetime]
    nurse_model: Optional[str]
    patient_model: Optional[str]
    correct_count: int
    total_count: int
    accuracy: float

class PatientCategoryStat(BaseModel):
    category: str
    total_instances: int
    avg_accuracy: float

class PatientStatsResponse(BaseModel):
    patient_id: str
    total_sessions: int
    sessions: List[PatientSessionStat]
    item_stats: List[PatientItemStat]
    category_stats: List[PatientCategoryStat]

# --- Global State ---
users_waiting = {}
users_session = {}

# --- Helper Functions (Top Level) ---
def get_id() -> str:
    base = f"{datetime.now().timestamp()}-{random()}"
    return sha1(base.encode()).hexdigest()

def get_current_prompt_versions(db: Session) -> dict:
    """現在アクティブなプロンプトのバージョンを取得"""
    try:
        prompt_db = modelDatabase.PromptSessionLocal()
        prompt_service = PromptTemplateService(prompt_db)
        
        versions = {}
        for template_type in ['patient', 'interviewer', 'evaluator']:
            template = prompt_service.get_active_template(template_type)
            versions[f"{template_type}_version"] = template.version if template else None
        
        prompt_db.close()
        return versions
    except Exception as e:
        logger.error(f"Failed to get current prompt versions: {e}")
        return {"patient_version": None, "interviewer_version": None, "evaluator_version": None}

async def get_assistant_model_info(assistant_id: str, oaw: OpenAIAssistantWrapper) -> str:
    """指定されたAssistant IDのモデル情報を取得"""
    if not assistant_id:
        logger.error("Assistant ID is missing")
        raise ValueError("Assistant ID is required")
    
    if not oaw:
        logger.error("OpenAI Assistant Wrapper is not available")
        raise ValueError("OpenAI Assistant Wrapper is required")
    
    try:
        assistant_info = await oaw.get_assistant_info(assistant_id)
        
        if not assistant_info:
            logger.error(f"No assistant info found for ID: {assistant_id}")
            raise ValueError(f"Assistant info not found for ID: {assistant_id}")
        
        model_name = assistant_info.get("model")
        if not model_name:
            logger.error(f"No model name found in assistant info for ID: {assistant_id}")
            raise ValueError(f"Model name not found for assistant ID: {assistant_id}")
        
        logger.info(f"Retrieved model name '{model_name}' for assistant ID: {assistant_id}")
        return model_name
        
    except Exception as e:
        logger.error(f"Failed to get assistant model info for ID {assistant_id}: {e}")
        raise

async def log_message(db: Session, session_id: str, user_name: str, patient_id: str, user_role: str, sender: str, message: str, logger, is_initial_message: bool = False, ai_role: str = None):
    if not modelDatabase.SessionLocal:
        return
    try:
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

async def _mark_session_completed(db: Session, session_id: str, logger):
    try:
        db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id
        ).update({modelDatabase.ChatLog.completed: True})
        db.commit()
        logger.debug(f"Session {session_id} marked as completed.")
    except Exception as e:
        logger.error(f"Failed to mark session as completed: {e}")
        db.rollback()

async def _save_history(session_id: str, history: History, logger) -> None:
    filename = f"history-{session_id}.json"
    with open(filename, "w", encoding="utf-8") as fd:
        json.dump(history.model_dump(exclude={'session_id'}), fd, ensure_ascii=False)
    logger.debug(f"History has been saved {filename}")

def _find_peer_human(user: UserDef) -> UserDef:
    peer_role = "保健師" if user.role == "患者" else "患者"
    for u in users_waiting.values():
        if u.role == peer_role and u.status == Status.Prepared.name:
            return u
    return None

def _get_conversation_end_detector_assistant_id() -> str:
    """assistants.jsonから4つ目のIDを会話終了検出専用Assistantとして取得"""
    try:
        assistants = json.load(open("assistants.json"))
        if len(assistants) >= 4:
            return assistants[3]  # 0-indexed
        else:
            raise ValueError(f"会話終了検出用Assistant IDが不足しています。assistants.jsonに最低4つのIDが必要です。現在: {len(assistants)}個")
    except FileNotFoundError:
        raise FileNotFoundError("assistants.jsonファイルが見つかりません")
    except json.JSONDecodeError as e:
        raise ValueError(f"assistants.jsonの形式が不正です: {e}")

def _find_peer_ai(user: UserDef) -> AssistantDef:
    assistants = json.load(open("assistants.json"))
    if user.role == "保健師":
        return AssistantDef(
            user_id=ai_get_id(), role="患者",
            assistant_id=assistants[0],
        )
    elif user.role == "患者":
        return AssistantDef(
            user_id=ai_get_id(), role="保健師",
            assistant_id=assistants[1],
        )
    elif user.role == "傍聴者":
        # 傍聴者の場合は特別処理が必要（AIConversationManagerで処理）
        return None
    return None

def _find_user_session(user_id: str) -> APISession:
    for s in users_session.values():
        for u in s.users:
            if u.user_id == user_id:
                return s
    return None

async def _execute_debriefing_with_specialist(session: APISession, user: UserDef, db: Session, logger, oaw: OpenAIAssistantWrapper, role_provider):
    """Debriefing専用Assistantを使用してクリーンな環境で評価を実行する"""
    
    if user.role not in ["保健師", "傍聴者"]:
        logger.info(f"Debriefing skipped for user role: {user.role}")
        await user.ws.send_json(SessionTerminated(session_id=session.session_id, reason="Session ended by user.").dict())
        await user.ws.close()
        return

    # Debriefing専用AssistantのIDを取得
    try:
        with open("assistants.json", "r") as f:
            assistants = json.load(f)
        if len(assistants) < 3:
            logger.error("Debriefing specialist assistant ID not found in assistants.json")
            debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 評価専用AIが設定されていません）"}
            await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_data=debriefing_data).dict())
            return
            
        debriefing_assistant_id = assistants[2]  # 3番目のAssistant ID
        logger.info(f"Using debriefing specialist assistant: {debriefing_assistant_id}")
    except Exception as e:
        logger.error(f"Failed to load debriefing assistant ID: {e}")
        debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 設定ファイルの読み込みエラー）"}
        await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_data=debriefing_data).dict())
        return

    # 新しいスレッドを作成してクリーンな環境を準備
    try:
        debriefing_thread_id = await oaw.create_thread()
        logger.info(f"Created debriefing thread: {debriefing_thread_id}")
    except Exception as e:
        logger.error(f"Failed to create debriefing thread: {e}")
        debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 評価環境の準備エラー）"}
        await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_data=debriefing_data).dict())
        return

    # Debriefing専用のAssistant定義を作成
    debriefing_assistant = AssistantDef(
        user_id=ai_get_id(),
        role="評価者",
        assistant_id=debriefing_assistant_id,
        thread_id=debriefing_thread_id
    )

    # 実際の評価AIモデル情報を取得してデータベースに保存
    try:
        evaluator_model = await get_assistant_model_info(debriefing_assistant_id, oaw)
        # セッションレコードを更新
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session.session_id).first()
        if db_session:
            db_session.evaluator_model = evaluator_model
            db.commit()
            logger.info(f"Updated session {session.session_id} with actual evaluator_model: {evaluator_model}")
        else:
            logger.error(f"Session {session.session_id} not found in database for evaluator model update")
    except Exception as e:
        logger.error(f"Failed to get/update evaluator model info for {debriefing_assistant_id}: {e}")
        # Continue with debriefing even if model info retrieval fails

    # Function Calling用のツール定義
    debriefing_tool = {
        "type": "function",
        "name": "submit_debriefing_report",
        "description": "ユーザー（保健師役）の聞き取りスキルに関する評価レポートを提出します。",
        "parameters": {
            "type": "object",
            "properties": {
                "overall_score": {
                    "type": "integer",
                    "description": "総合評価（100点満点）"
                },
                "information_retrieval_ratio": {
                    "type": "string",
                    "description": "感染経路の特定や濃厚接触者の把握に繋がる重要な情報を、これまでの会話からどの程度の割合で聴取できたかの評価。詳細なフィードバックをお願いします。"
                },
                "information_quality": {
                    "type": "string",
                    "description": "患者役が回答した情報の質。どれだけ効率的に情報を引き出せたかの指標。詳細なフィードバックをお願いします。"
                },
                "micro_evaluations": {
                    "type": "array",
                    "description": "ユーザーの個々の発言に対するミクロな評価のリスト。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "utterance": {"type": "string", "description": "評価対象のユーザーの発言"},
                            "evaluation_symbol": {"type": "string", "enum": ["◎", "○", "△", "✕"], "description": "記号による評価"},
                            "advice": {"type": "string", "description": "具体的なアドバイス"}
                        },
                        "required": ["utterance", "evaluation_symbol", "advice"]
                    }
                },
                "missed_points": {
                    "type": "array",
                    "description": "保健師が聞き出せなかった重要なポイントのリスト。患者の設定情報（正解データ）と対話履歴を詳細に比較し、感染経路追跡や濃厚接触者特定に必要だが聞き取れなかった情報を具体的に指摘する。抽象的な指摘ではなく、実際の日付、場所、人物名、行動内容などの具体的な情報を明記すること。ただし、評価の対象とする条件は次の通りです。これらすべてを同時に満たす場合のみ出力してください。そのうえで、特に聞き漏らしがなければ何も出力しないでください。1. 患者情報として与えられている情報であること。2. 感染経路調査上重要と思われること。3. 聞き出せなかった情報であること。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "description": "カテゴリ（例：発症経緯、行動履歴、接触者情報、症状詳細、感染源調査など）"},
                            "detail": {"type": "string", "description": "具体的に聞き出せなかった情報の内容。抽象的な表現ではなく、実際の日付、時刻、場所名、人物名、行動の詳細など、患者の設定情報に含まれている具体的な事実を明記すること。例：「4月5日の午後にA店で30分間滞在したこと」「同居家族のB氏が4月3日に発熱していたこと」など。"},
                            "importance": {"type": "string", "enum": ["高", "中", "低"], "description": "疫学調査における重要度"}
                        },
                        "required": ["category", "detail", "importance"]
                    }
                },
                "overall_comment": {
                    "type": "string",
                    "description": "全体的な総評。"
                }
            },
            "required": ["overall_score", "information_retrieval_ratio", "information_quality", "micro_evaluations", "missed_points", "overall_comment"]
        }
    }

    # 対話履歴を整形
    conversation_history = "\n".join([
        f"{msg.role}: {msg.text}" 
        for msg in session.history.history 
        if msg.role in ["保健師", "患者"]
    ])
    
    # デバッグログ: 対話履歴の詳細
    # logger.info(f"[DEBRIEFING DEBUG] Session history contains {len(session.history.history)} total messages")
    # relevant_messages = [msg for msg in session.history.history if msg.role in ["保健師", "患者"]]
    # logger.info(f"[DEBRIEFING DEBUG] Relevant messages for evaluation: {len(relevant_messages)}")
    
    # for i, msg in enumerate(relevant_messages):
    #     logger.info(f"[DEBRIEFING DEBUG] Message {i+1}: Role='{msg.role}', Length={len(msg.text)} chars")
    #     logger.info(f"[DEBRIEFING DEBUG] Message {i+1} Content: {msg.text[:200]}{'...' if len(msg.text) > 200 else ''}")
    
    # logger.info(f"[DEBRIEFING DEBUG] Final conversation_history length: {len(conversation_history)} chars")
    # logger.info(f"[DEBRIEFING DEBUG] Conversation history preview: {conversation_history[:500]}{'...' if len(conversation_history) > 500 else ''}")
    
    # 患者の初期設定情報を取得（評価者AIが正解を知るため）
    patient_setting_info = ""
    try:
        # 患者IDを特定
        patient_id = None
        # logger.info(f"[DEBRIEFING DEBUG] Session has {len(session.users)} users")
        for i, u in enumerate(session.users):
            # logger.info(f"[DEBRIEFING DEBUG] User {i+1}: type={type(u).__name__}, has_target_patient_id={hasattr(u, 'target_patient_id')}")
            if hasattr(u, 'target_patient_id'):
                # logger.info(f"[DEBRIEFING DEBUG] User {i+1} target_patient_id: {u.target_patient_id}")
                if u.target_patient_id:
                    patient_id = u.target_patient_id
                    break
        
        # logger.info(f"[DEBRIEFING DEBUG] Determined patient_id: {patient_id}")
        
        if patient_id and role_provider:
            # 患者の詳細情報を取得
            patient_details = role_provider.get_patient_details(patient_id)
            # logger.info(f"[DEBRIEFING DEBUG] Patient details retrieved: {patient_details is not None}")
            if patient_details:
                # logger.info(f"[DEBRIEFING DEBUG] Patient details keys: {list(patient_details.keys()) if patient_details else 'None'}")
                
                # 面接日を特定（セッション履歴から取得）
                interview_date_str = None
                system_messages = [msg for msg in session.history.history if msg.role == "system"]
                # logger.info(f"[DEBRIEFING DEBUG] Found {len(system_messages)} system messages")
                
                for i, msg in enumerate(system_messages):
                    # logger.info(f"[DEBRIEFING DEBUG] System message {i+1}: {msg.text[:100]}{'...' if len(msg.text) > 100 else ''}")
                    if "面接日：" in msg.text:
                        import re
                        match = re.search(r'面接日：(\d{4}-\d{2}-\d{2})', msg.text)
                        if match:
                            # 日付形式を get_patient_prompt_chunks が期待する形式に変換
                            date_parts = match.group(1).split('-')
                            interview_date_str = f"{date_parts[0]}年{date_parts[1]}月{date_parts[2]}日"
                            # logger.info(f"[DEBRIEFING DEBUG] Found interview_date_str: {interview_date_str}")
                            break
                
                # logger.info(f"[DEBRIEFING DEBUG] Final interview_date_str: {interview_date_str}")
                
                # 患者プロンプトの全情報を取得（評価者が正解を知るため）
                prompt_chunks, calculated_interview_date = role_provider.get_patient_prompt_chunks(patient_id, interview_date_str)
                # logger.info(f"[DEBRIEFING DEBUG] Patient prompt chunks: {len(prompt_chunks)} chunks")
                # logger.info(f"[DEBRIEFING DEBUG] Calculated interview date: {calculated_interview_date}")
                
                # for i, chunk in enumerate(prompt_chunks):
                #     logger.info(f"[DEBRIEFING DEBUG] Chunk {i+1} length: {len(chunk)} chars")
                #     logger.info(f"[DEBRIEFING DEBUG] Chunk {i+1} preview: {chunk[:200]}{'...' if len(chunk) > 200 else ''}")
                
                patient_setting_info = "\n".join(prompt_chunks)
                # logger.info(f"[DEBRIEFING DEBUG] Final patient_setting_info length: {len(patient_setting_info)} chars")
                logger.info(f"Retrieved patient setting information for evaluation (patient_id: {patient_id})")
            else:
                logger.warning(f"Could not retrieve patient details for patient_id: {patient_id}")
        else:
            logger.warning(f"Could not determine patient_id for debriefing evaluation. patient_id={patient_id}, role_provider={role_provider is not None}")
    except Exception as e:
        logger.error(f"Failed to retrieve patient setting information for evaluation: {e}")
        import traceback
        # logger.error(f"[DEBRIEFING DEBUG] Full traceback: {traceback.format_exc()}")
        patient_setting_info = ""
    
    # DB から評価AIプロンプトを取得
    try:
        prompt_db = modelDatabase.PromptSessionLocal()
        prompt_service = PromptTemplateService(prompt_db)
        evaluator_template = prompt_service.get_active_template('evaluator')
        prompt_db.close()
        
        if evaluator_template:
            base_prompt = evaluator_template.prompt_text
            # logger.info(f"[DEBRIEFING DEBUG] Using evaluator template from DB (version: {evaluator_template.version})")
            # logger.info(f"[DEBRIEFING DEBUG] Base prompt length: {len(base_prompt)} chars")
            # logger.info(f"[DEBRIEFING DEBUG] Base prompt preview: {base_prompt[:300]}{'...' if len(base_prompt) > 300 else ''}")
        else:
            # フォールバック（DBに登録されていない場合）
            base_prompt = """あなたは保健師の聞き取りスキルを評価する専門家です。以下の患者の設定情報と対話履歴を分析し、`submit_debriefing_report`関数を呼び出して詳細な評価レポートを作成してください。

**重要**: 聞き出せなかったポイント(missed_points)を評価する際は、患者の設定情報（正解データ）と対話履歴を詳細に比較し、抽象的な指摘ではなく具体的な情報を明記してください。

例：
- 良い例：「4月5日の14:00-14:30にスーパーマーケットAで買い物をしたこと」
- 悪い例：「買い物の詳細について」

日付、時刻、場所名、人物名、行動の詳細など、患者データに含まれている具体的な事実を正確に記述してください。"""
            logger.warning("Evaluator template not found in DB, using fallback prompt")
    except Exception as e:
        # エラー時のフォールバック
        base_prompt = """あなたは保健師の聞き取りスキルを評価する専門家です。以下の患者の設定情報と対話履歴を分析し、`submit_debriefing_report`関数を呼び出して詳細な評価レポートを作成してください。

**重要**: 聞き出せなかったポイント(missed_points)を評価する際は、患者の設定情報（正解データ）と対話履歴を詳細に比較し、抽象的な指摘ではなく具体的な情報を明記してください。

例：
- 良い例：「4月5日の14:00-14:30にスーパーマーケットAで買い物をしたこと」
- 悪い例：「買い物の詳細について」

日付、時刻、場所名、人物名、行動の詳細など、患者データに含まれている具体的な事実を正確に記述してください。"""
        logger.error(f"Failed to load evaluator template: {e}")
    
    # 完全なプロンプトを作成（分割送信用）
    full_prompt = base_prompt + "\n\n"
    
    if patient_setting_info:
        full_prompt += f"【患者の設定情報（正解データ）】\n{patient_setting_info}\n\n"
        # logger.info(f"[DEBRIEFING DEBUG] Added patient setting info section")
    else:
        pass
        # logger.warning(f"[DEBRIEFING DEBUG] No patient setting info available!")
    
    full_prompt += f"【対話履歴】\n{conversation_history}\n\n"
    # logger.info(f"[DEBRIEFING DEBUG] Added conversation history section")
    
    # 具体的な指示を追加
    additional_instructions = """以上の患者の設定情報と対話履歴を詳細に比較し、詳細な評価レポートを作成してください。"""
    full_prompt += additional_instructions
    
    # logger.info(f"[DEBRIEFING DEBUG] Final full_prompt length: {len(full_prompt)} chars")
    # logger.info(f"[DEBRIEFING DEBUG] Full prompt structure analysis:")
    # logger.info(f"[DEBRIEFING DEBUG]   - Base prompt: {len(base_prompt)} chars")
    # logger.info(f"[DEBRIEFING DEBUG]   - Patient info: {len(patient_setting_info)} chars")
    # logger.info(f"[DEBRIEFING DEBUG]   - Conversation: {len(conversation_history)} chars")
    # logger.info(f"[DEBRIEFING DEBUG]   - Instructions: {len(additional_instructions)} chars")

    try:
        # プロンプトを分割送信（患者AIと同じ方法）
        prompt_chunks = role_provider._split_text_for_prompt(full_prompt, 2000)
        logger.info(f"Split evaluator prompt into {len(prompt_chunks)} chunks for debriefing")
        
        # 分割されたプロンプトを順次送信
        for i, chunk in enumerate(prompt_chunks):
            # logger.info(f"[DEBRIEFING DATA] === CHUNK {i+1}/{len(prompt_chunks)} START ===")
            # logger.info(f"[DEBRIEFING DATA] {chunk}")
            # logger.info(f"[DEBRIEFING DATA] === CHUNK {i+1}/{len(prompt_chunks)} END ===")
            
            if i == 0:
                # 最初のチャンクは通常のメッセージとして送信
                await oaw.add_message_to_thread(debriefing_assistant.thread_id, chunk)
                logger.info(f"Sent evaluator prompt chunk {i+1}/{len(prompt_chunks)} to thread")
            else:
                # 残りのチャンクも追加のメッセージとして送信
                await oaw.add_message_to_thread(debriefing_assistant.thread_id, chunk)
                logger.info(f"Sent evaluator prompt chunk {i+1}/{len(prompt_chunks)} to thread")
        
        # 最後に評価実行指示を送信してツールを呼び出し
        final_instruction = "上記の情報を分析し、`submit_debriefing_report`関数を呼び出して詳細な評価レポートを作成してください。"
        # logger.info(f"[DEBRIEFING DATA] === FINAL INSTRUCTION START ===")
        # logger.info(f"[DEBRIEFING DATA] {final_instruction}")
        # logger.info(f"[DEBRIEFING DATA] === FINAL INSTRUCTION END ===")
        
        # logger.info(f"[DEBRIEFING DEBUG] Using tool_choice: submit_debriefing_report")
        # logger.info(f"[DEBRIEFING DEBUG] Max retries set to: 5")
        
        # 評価を実行（レート制限対策でリトライ回数を増加）
        # logger.info(f"[DEBRIEFING DEBUG] Starting OpenAI API call for evaluation...")
        response_text, tool_call = await oaw.send_message(
            debriefing_assistant,
            final_instruction,
            tools=[debriefing_tool],
            tool_choice="required",
            max_retries=5  # 評価者AIは重要なので、より多くのリトライを許可
        )
        
        # logger.info(f"[DEBRIEFING DEBUG] OpenAI API call completed")
        # logger.info(f"[DEBRIEFING DEBUG] Response text: {response_text}")
        # logger.info(f"[DEBRIEFING DEBUG] Tool call received: {tool_call is not None}")
        # if tool_call:
        #     logger.info(f"[DEBRIEFING DEBUG] Tool call function name: {tool_call.name}")
        #     logger.info(f"[DEBRIEFING DEBUG] Tool call arguments length: {len(tool_call.arguments)} chars")

        debriefing_data = None
        if tool_call and tool_call.name == "submit_debriefing_report":
            # logger.info(f"[DEBRIEFING DEBUG] Processing tool call 'submit_debriefing_report'")
            # logger.info(f"[DEBRIEFING DATA] === LLM RESPONSE FULL START ===")
            # logger.info(f"[DEBRIEFING DATA] {tool_call.arguments}")
            # logger.info(f"[DEBRIEFING DATA] === LLM RESPONSE FULL END ===")
            try:
                args = json.loads(tool_call.arguments)
                # logger.info(f"[DEBRIEFING DEBUG] JSON parsing successful")
                # logger.info(f"[DEBRIEFING DEBUG] Parsed data keys: {list(args.keys()) if isinstance(args, dict) else 'Not a dict'}")
                
                # 各フィールドの詳細ログ
                # if isinstance(args, dict):
                #     logger.info(f"[DEBRIEFING DEBUG] overall_score: {args.get('overall_score', 'Missing')}")
                #     logger.info(f"[DEBRIEFING DEBUG] micro_evaluations count: {len(args.get('micro_evaluations', [])) if 'micro_evaluations' in args else 'Missing'}")
                #     logger.info(f"[DEBRIEFING DEBUG] missed_points count: {len(args.get('missed_points', [])) if 'missed_points' in args else 'Missing'}")
                #     logger.info(f"[DEBRIEFING DEBUG] information_retrieval_ratio length: {len(str(args.get('information_retrieval_ratio', '')))}")
                #     logger.info(f"[DEBRIEFING DEBUG] information_quality length: {len(str(args.get('information_quality', '')))}")
                #     logger.info(f"[DEBRIEFING DEBUG] overall_comment length: {len(str(args.get('overall_comment', '')))}")
                
                debriefing_data = args
                logger.info("Successfully parsed debriefing report from specialist assistant.")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"[DEBRIEFING DEBUG] JSON parsing failed: {e}")
                logger.error(f"[DEBRIEFING DEBUG] Failed to parse debriefing tool call arguments: {e}")
                logger.error(f"[DEBRIEFING DEBUG] Raw arguments (first 500 chars): {tool_call.arguments[:500] if tool_call.arguments else 'None'}")
                logger.error(f"[DEBRIEFING DEBUG] Raw arguments (last 500 chars): {tool_call.arguments[-500:] if tool_call.arguments and len(tool_call.arguments) > 500 else 'N/A'}")
                logger.error(f"[DEBRIEFING DEBUG] Arguments length: {len(tool_call.arguments) if tool_call.arguments else 0}")

                # エラー位置周辺の文字を確認
                if tool_call.arguments and len(tool_call.arguments) > 1911:
                    error_context = tool_call.arguments[1900:1920]
                    logger.error(f"[DEBRIEFING DEBUG] Error context around char 1912: '{error_context}'")
                
                import traceback
                logger.error(f"[DEBRIEFING DEBUG] Full parsing traceback: {traceback.format_exc()}")
                
                # 部分的なJSON修復を試行
                try:
                    # 不完全なJSONの場合、閉じ括弧を追加して修復を試みる
                    raw_args = tool_call.arguments.strip()
                    if raw_args and not raw_args.endswith('}'):
                        logger.info("[DEBRIEFING DEBUG] Attempting to repair incomplete JSON...")
                        # 最後の完全なフィールドまでを取得
                        last_quote_pos = raw_args.rfind('"')
                        if last_quote_pos > 0:
                            # 最後の引用符以降を削除して閉じ括弧を追加
                            repaired_json = raw_args[:last_quote_pos + 1]
                            if repaired_json.count('{') > repaired_json.count('}'):
                                repaired_json += '}'
                            args = json.loads(repaired_json)
                            logger.info("[DEBRIEFING DEBUG] Successfully repaired and parsed incomplete JSON")
                            debriefing_data = args
                        else:
                            raise ValueError("Cannot repair JSON")
                    else:
                        raise ValueError("Cannot repair JSON")
                except Exception as repair_error:
                    logger.error(f"[DEBRIEFING DEBUG] JSON repair failed: {repair_error}")
                    logger.error(f"Failed to parse debriefing tool call arguments: {e}")
                    debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 評価データの解析エラー）"}
        else:
            # logger.error(f"[DEBRIEFING DEBUG] Unexpected tool call result")
            # logger.error(f"[DEBRIEFING DEBUG] tool_call is None: {tool_call is None}")
            # if tool_call:
            #     logger.error(f"[DEBRIEFING DEBUG] tool_call.name: {getattr(tool_call, 'name', 'No name attribute')}")
            logger.error(f"Debriefing failed. Expected tool call 'submit_debriefing_report' but got: {tool_call}")
            debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: AIが評価データを生成できませんでした）"}

    except Exception as e:
        logger.error(f"Exception during debriefing execution: {e}")
        import traceback
        # logger.error(f"[DEBRIEFING DEBUG] Full exception traceback: {traceback.format_exc()}")
        debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 処理中にエラーが発生しました）"}

    finally:
        # スレッドを削除してリソースを解放
        thread_to_delete = None
        if 'debriefing_assistant' in locals() and debriefing_assistant and debriefing_assistant.thread_id:
            thread_to_delete = debriefing_assistant.thread_id
            try:
                await oaw.delete_thread(debriefing_assistant)
                logger.info(f"Deleted debriefing thread: {thread_to_delete}")
            except Exception as e:
                logger.warning(f"Failed to delete debriefing thread {thread_to_delete}: {e}")
        elif 'debriefing_thread_id' in locals() and debriefing_thread_id:
            thread_to_delete = debriefing_thread_id
            try:
                await oaw.delete_thread_by_id(debriefing_thread_id)
                logger.info(f"Deleted debriefing thread: {thread_to_delete}")
            except Exception as e:
                logger.warning(f"Failed to delete debriefing thread {thread_to_delete}: {e}")

    # 結果をクライアントに送信
    # logger.info(f"[DEBRIEFING DEBUG] Final debriefing_data type: {type(debriefing_data)}")
    # logger.info(f"[DEBRIEFING DEBUG] Final debriefing_data keys: {list(debriefing_data.keys()) if isinstance(debriefing_data, dict) else 'Not a dict'}")
    # if isinstance(debriefing_data, dict) and 'error' not in debriefing_data:
    #     logger.info(f"[DEBRIEFING DEBUG] Successfully generated evaluation report")
    # else:
    #     logger.warning(f"[DEBRIEFING DEBUG] Debriefing failed or contains error")
    
    await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_data=debriefing_data).dict())

    # ログに保存
    await log_message(db, session.session_id, "System", debriefing_assistant_id, "評価者", "System", f"Debriefing Data: {json.dumps(debriefing_data, ensure_ascii=False)}", logger)

    # チャットログにシステムメッセージとして評価レポートへのリンクを追加
    debriefing_link_message = f" 評価レポートが完成しました。[レポートを表示](/debriefing/{session.session_id})"
    await log_message(db, session.session_id, user.user_name, debriefing_assistant_id, "評価者", "System", debriefing_link_message, logger)

    # Debriefing完了後にセッションstatusをcompletedに更新
    try:
        db_session = db.query(SessionModel).filter(SessionModel.session_id == session.session_id).first()
        if db_session and db_session.status != 'completed':
            db_session.status = 'completed'
            db_session.completed_at = datetime.now()
            db.commit()
            logger.info(f"Session {session.session_id} marked as completed after debriefing")
    except Exception as e:
        logger.error(f"Failed to update session status after debriefing: {e}")
        db.rollback()


async def _execute_debriefing(session: APISession, user: UserDef, db: Session, logger, oaw: OpenAIAssistantWrapper, role_provider):
    """Debriefing処理を実行し、結果をクライアントに送信する"""
    # 新しい専用Assistantを使用したDebriefing処理に移行
    await _execute_debriefing_with_specialist(session, user, db, logger, oaw, role_provider)


# --- Main API Factory ---
def api(config):
    logger = config.logger
    oaw = OpenAIAssistantWrapper(config)
    role_provider = PatientRoleProvider(config)
    batch_runner = IRTBatchRunner(oaw, role_provider)

    app = FastAPI()

    @app.on_event("startup")
    async def startup_event():
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            logger.info("Initializing Database...")
            modelDatabase.initialize_database(db_url)
            modelDatabase.init_db()
            logger.info("Database initialized.")
        else:
            logger.warning("DATABASE_URL is not set. Running without database logging.")
        
        logger.info("Initializing PatientRoleProvider...")
        try:
            await role_provider.initialize()
            logger.info("PatientRoleProvider initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize PatientRoleProvider: {e}")
            
        # Initialize default prompts
        if modelDatabase.PromptSessionLocal:
            logger.info("Initializing default prompts...")
            try:
                db = modelDatabase.PromptSessionLocal()
                initialize_default_prompts(db)
                db.close()
                logger.info("Default prompts initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize default prompts: {e}")

    def get_db():
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
        db = modelDatabase.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def get_db_for_prompts():
        # プロンプト管理用のデータベースセッション（共通DB使用）
        if not modelDatabase.PromptSessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
        db = modelDatabase.PromptSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # --- API Endpoints ---
    @app.get("/v1/patients")
    async def get_available_patients():
        if role_provider.df is None:
            raise HTTPException(status_code=503, detail="Patient data is not ready.")
        return {"patient_ids": role_provider.get_available_patient_ids()}

    @app.get("/v1/patients/details")
    async def get_all_patient_details():
        if role_provider.df is None:
            raise HTTPException(status_code=503, detail="Patient data is not ready.")
        
        patient_ids = role_provider.get_available_patient_ids()
        patient_details = []
        
        for patient_id in patient_ids:
            details = role_provider.get_patient_details(patient_id)
            if "error" not in details:
                patient_details.append(details)
        
        return patient_details

    @app.get("/v1/patient/{patient_id}")
    async def get_patient_details(patient_id: str):
        if role_provider.df is None:
            raise HTTPException(status_code=503, detail="Patient data is not ready.")
        details = role_provider.get_patient_details(patient_id)
        if "error" in details:
            raise HTTPException(status_code=404, detail=details['error'])
        return details

    @db_retry(max_retries=3, delay=1.0, backoff=2.0)
    def _get_session_from_db(db: Session, session_id: str):
        """データベースからセッション情報を取得（リトライ機能付き）"""
        return db.query(SessionModel).filter(
            SessionModel.session_id == session_id,
            SessionModel.status.in_(['active', 'completed'])
        ).first()

    @app.get("/v1/session/{session_id}")
    async def get_session_status(session_id: str, db: Session = Depends(get_db)):
        """指定されたセッションが再開可能か確認し、関連情報を返す"""
        logger.info(f"Attempting to restore session with session_id: {session_id}") # DEBUG LOG
        
        try:
            db_session = _get_session_from_db(db, session_id)
        except Exception as e:
            logger.error(f"Failed to fetch session {session_id} from database: {e}")
            raise HTTPException(status_code=503, detail="Database connection error. Please try again later.")

        if not db_session:
            raise HTTPException(status_code=404, detail="Active session not found.")

        # 傍聴者の場合はセッション復元をサポートしない（ただし評価レポート表示のための情報取得は許可）
        # if db_session.user_role == "傍聴者":
        #     raise HTTPException(status_code=400, detail="Session restoration is not supported for observer role.")

        # If session is found, proceed to gather history and other details
        if role_provider.df is None:
            logger.warning("Role provider not initialized in get_session_status. Initializing...")
            await role_provider.initialize()
            if role_provider.df is None:
                raise HTTPException(status_code=503, detail="Patient data could not be loaded on demand.")

        history_logs = db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id,
            modelDatabase.ChatLog.sender != 'System',  # システムログは除外
            modelDatabase.ChatLog.is_initial_message == False # 初期メッセージは除外
        ).order_by(modelDatabase.ChatLog.created_at.asc()).all()

        chat_history = []
        user_icon = 'mdi-account-tie-woman' if db_session.user_role == '保健師' else 'mdi-account'
        assistant_icon = 'mdi-account' if db_session.user_role == '保健師' else 'mdi-account-tie-woman'

        for log in history_logs:
            if log.sender == 'User':
                chat_history.append({
                    "sender": "user",
                    "message": log.message,
                    "icon": user_icon
                })
            elif log.sender == 'Assistant':
                chat_history.append({
                    "sender": "assistant",
                    "message": log.message,
                    "icon": assistant_icon
                })

        patient_info = {}
        if db_session.patient_id:
            patient_info = role_provider.get_patient_details(db_session.patient_id)

        # Check if debriefing report exists for this session
        debriefing_exists = False
        if db_session.user_role == '保健師':
            debriefing_log = db.query(modelDatabase.ChatLog).filter(
                modelDatabase.ChatLog.session_id == session_id,
                modelDatabase.ChatLog.sender == "System",
                modelDatabase.ChatLog.message.like("Debriefing Data:%")
            ).first()
            
            if debriefing_log:
                debriefing_exists = True
                # Add system message to chat history if debriefing report exists
                debriefing_link_message = f" 評価レポートが完成しました。[レポートを表示](/debriefing/{session_id})"
                # Check if this message already exists in history
                existing_link = any(
                    msg.get("sender") == "system" and "評価レポートが完成しました" in msg.get("message", "")
                    for msg in chat_history
                )
                if not existing_link:
                    chat_history.append({
                        "sender": "system",
                        "message": debriefing_link_message,
                        "icon": "mdi-file-chart"
                    })

        # Create a new user_id for the restored session to allow reconnection
        new_user_id = ai_get_id()
        restored_user = UserDef(
            user_id=new_user_id,
            user_name=db_session.user_name,
            role=db_session.user_role,
            status=Status.Registered.name, # Set as Registered to allow WS connection
            target_patient_id=db_session.patient_id,
            session_id=session_id # Pass the session_id for reconnection
        )
        users_waiting[new_user_id] = restored_user

        return {
            "session_id": session_id,
            "user_id": new_user_id, # Return the NEW user_id
            "user_name": db_session.user_name,
            "user_role": db_session.user_role,
            "patient_id": db_session.patient_id,
            "chat_history": chat_history,
            "patient_info": patient_info,
            "interview_date": db_session.interview_date or db_session.created_at.strftime("%Y年%m月%d日"),
            "debriefing_exists": debriefing_exists,
            "prompt_versions": {
                "patient_version": db_session.patient_version,
                "interviewer_version": db_session.interviewer_version,
                "evaluator_version": db_session.evaluator_version
            },
            "model_names": {
                "patient_model": db_session.patient_model,
                "interviewer_model": db_session.interviewer_model,
                "evaluator_model": db_session.evaluator_model
            }
        }

    @db_retry(max_retries=3, delay=1.0, backoff=2.0)
    def _get_sessions_from_db(db: Session):
        """データベースからセッション一覧を取得（リトライ機能付き）"""
        return db.query(SessionModel).order_by(
            desc(SessionModel.created_at)
        ).all()

    @app.get("/v1/logs")
    async def get_logs(db: Session = Depends(get_db)):
        """対話ログのセッション一覧を取得する"""
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")

        try:
            sessions = _get_sessions_from_db(db)
        except Exception as e:
            logger.error(f"Failed to fetch sessions from database: {e}")
            raise HTTPException(status_code=503, detail="Database connection error. Please try again later.")
        
        return [
            {
                "session_id": session.session_id,
                "user_name": session.user_name,
                "user_role": session.user_role,
                "patient_id": session.patient_id,
                "started_at": session.created_at.isoformat()
            } for session in sessions
        ]

    @db_retry(max_retries=3, delay=1.0, backoff=2.0)
    def _get_chat_logs_from_db(db: Session, session_id: str):
        """データベースからチャットログを取得（リトライ機能付き）"""
        return db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id
        ).order_by(
            modelDatabase.ChatLog.created_at
        ).all()

    @app.get("/v1/logs/{session_id}")
    async def get_log_detail(session_id: str, db: Session = Depends(get_db)):
        """特定のセッションの対話ログ詳細を取得する"""
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
            
        try:
            logs = _get_chat_logs_from_db(db, session_id)
        except Exception as e:
            logger.error(f"Failed to fetch chat logs for session {session_id}: {e}")
            raise HTTPException(status_code=503, detail="Database connection error. Please try again later.")
        
        if not logs:
            raise HTTPException(status_code=404, detail="Session not found")
            
        return [
            {
                "id": log.id,
                "sender": log.sender,
                "role": log.user_role,
                "ai_role": log.ai_role,
                "message": log.message,
                "created_at": log.created_at.isoformat()
            } for log in logs
        ]

    @app.get("/v1/session/{session_id}/debriefing")
    async def get_debriefing_data(session_id: str, db: Session = Depends(get_db)):
        """特定のセッションのデブリーフィングデータを取得する"""
        if not modelDatabase.SessionLocal:
            raise HTTPException(status_code=503, detail="Database is not initialized.")
            
        # Debriefingデータはsender='System'でmessageに'Debriefing Data:'で始まるJSONとして保存されている
        debriefing_log = db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id,
            modelDatabase.ChatLog.sender == "System",
            modelDatabase.ChatLog.message.like("Debriefing Data:%")
        ).order_by(
            modelDatabase.ChatLog.created_at.desc()
        ).first()
        
        if not debriefing_log:
            raise HTTPException(status_code=404, detail="Debriefing data not found for this session")
        
        try:
            # "Debriefing Data: " プレフィックスを削除してJSONを解析
            debriefing_json = debriefing_log.message.replace("Debriefing Data: ", "", 1)
            debriefing_data = json.loads(debriefing_json)
            return debriefing_data
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse debriefing data for session {session_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to parse debriefing data")

    # --- Prompt Management API ---
    @app.get("/v1/prompts")
    async def get_all_prompts(template_type: Optional[str] = None, db: Session = Depends(get_db_for_prompts)):
        """全てのプロンプトテンプレートを取得"""        
        service = PromptTemplateService(db)
        templates = service.get_all_templates(template_type)
        
        return [
            PromptTemplateResponse(
                id=t.id,
                template_type=t.template_type,
                version=t.version,
                prompt_text=t.prompt_text,
                message_text=t.message_text,
                description=t.description,
                is_active=t.is_active,
                created_at=t.created_at
            ) for t in templates
        ]

    @app.get("/v1/prompts/{template_type}/active")
    async def get_active_prompt(template_type: str, db: Session = Depends(get_db_for_prompts)):
        """指定されたtypeのアクティブなプロンプトを取得"""
        service = PromptTemplateService(db)
        template = service.get_active_template(template_type)
        
        if not template:
            raise HTTPException(status_code=404, detail="Active template not found")
        
        return PromptTemplateResponse(
            id=template.id,
            template_type=template.template_type,
            version=template.version,
            prompt_text=template.prompt_text,
            message_text=template.message_text,
            description=template.description,
            is_active=template.is_active,
            created_at=template.created_at
        )

    @app.post("/v1/prompts")
    async def create_prompt(req: PromptTemplateRequest, db: Session = Depends(get_db_for_prompts)):
        """新しいプロンプトテンプレートを作成"""
        # バリデーション
        if req.template_type not in ['patient', 'interviewer', 'evaluator']:
            raise HTTPException(status_code=400, detail="Invalid template_type")
        
        service = PromptTemplateService(db)
        template = service.create_template(
            template_type=req.template_type,
            prompt_text=req.prompt_text,
            message_text=req.message_text,
            description=req.description
        )
        
        return PromptTemplateResponse(
            id=template.id,
            template_type=template.template_type,
            version=template.version,
            prompt_text=template.prompt_text,
            message_text=template.message_text,
            description=template.description,
            is_active=template.is_active,
            created_at=template.created_at
        )

    @app.put("/v1/prompts/{template_id}")
    async def update_prompt(template_id: int, req: PromptTemplateRequest, db: Session = Depends(get_db_for_prompts)):
        """既存のプロンプトテンプレートを更新"""
        service = PromptTemplateService(db)
        template = service.update_template(
            template_id=template_id,
            prompt_text=req.prompt_text,
            message_text=req.message_text,
            description=req.description
        )
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return PromptTemplateResponse(
            id=template.id,
            template_type=template.template_type,
            version=template.version,
            prompt_text=template.prompt_text,
            message_text=template.message_text,
            description=template.description,
            is_active=template.is_active,
            created_at=template.created_at
        )

    @app.post("/v1/prompts/{template_id}/activate")
    async def activate_prompt(template_id: int, db: Session = Depends(get_db_for_prompts)):
        """指定されたプロンプトテンプレートをアクティブにする"""
        service = PromptTemplateService(db)
        template = service.activate_template(template_id)
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        return PromptTemplateResponse(
            id=template.id,
            template_type=template.template_type,
            version=template.version,
            prompt_text=template.prompt_text,
            message_text=template.message_text,
            description=template.description,
            is_active=template.is_active,
            created_at=template.created_at
        )

    # --- IRT Item Catalog API ---
    @app.get("/v1/irt/item-types")
    async def get_irt_item_types(
        catalog_version: Optional[int] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        db: Session = Depends(get_db)
    ):
        """IRT項目タイプ一覧を取得"""
        service = IRTItemTypeService(db)
        items = service.get_all_item_types(catalog_version=catalog_version, category=category, status=status)
        return [
            IRTItemTypeResponse(
                id=it.id, catalog_version=it.catalog_version, code=it.code,
                category=it.category, name_ja=it.name_ja, name_en=it.name_en,
                description=it.description, investigation_phase=it.investigation_phase,
                pdf_priority=it.pdf_priority, investigation_direction=it.investigation_direction,
                frequency=it.frequency, intensity=it.intensity, status=it.status,
                created_at=it.created_at
            ) for it in items
        ]

    @app.get("/v1/irt/item-types/{code}")
    async def get_irt_item_type(code: str, catalog_version: Optional[int] = None, db: Session = Depends(get_db)):
        """コードでIRT項目タイプを取得"""
        service = IRTItemTypeService(db)
        it = service.get_item_type_by_code(code, catalog_version=catalog_version)
        if not it:
            raise HTTPException(status_code=404, detail="Item type not found")
        return IRTItemTypeResponse(
            id=it.id, catalog_version=it.catalog_version, code=it.code,
            category=it.category, name_ja=it.name_ja, name_en=it.name_en,
            description=it.description, investigation_phase=it.investigation_phase,
            pdf_priority=it.pdf_priority, investigation_direction=it.investigation_direction,
            frequency=it.frequency, intensity=it.intensity, status=it.status,
            created_at=it.created_at
        )

    @app.post("/v1/irt/item-types/bulk")
    async def bulk_create_irt_item_types(req: IRTItemTypeBulkRequest, db: Session = Depends(get_db)):
        """IRT項目タイプを一括登録"""
        service = IRTItemTypeService(db)
        created = service.bulk_create_item_types(req.items)
        return {"created": len(created)}

    @app.get("/v1/irt/patient-instances/{patient_id}")
    async def get_irt_patient_instances(
        patient_id: str,
        catalog_version: Optional[int] = None,
        db: Session = Depends(get_db)
    ):
        """患者IDでIRTインスタンス一覧を取得"""
        service = IRTPatientInstanceService(db)
        instances = service.get_instances_for_patient(patient_id, catalog_version=catalog_version)
        return [
            IRTPatientInstanceResponse(
                id=inst.id, catalog_version=inst.catalog_version, patient_id=inst.patient_id,
                item_type_code=inst.item_type_code, instance_number=inst.instance_number,
                date=inst.date, description=inst.description,
                investigation_direction_override=inst.investigation_direction_override,
                scene_category=inst.scene_category,
                density_closed=inst.density_closed, density_crowded=inst.density_crowded,
                density_close_contact=inst.density_close_contact,
                related_patient_ids=inst.related_patient_ids,
                is_detectable=inst.is_detectable, notes=inst.notes,
                created_at=inst.created_at
            ) for inst in instances
        ]

    @app.post("/v1/irt/patient-instances/bulk")
    async def bulk_create_irt_patient_instances(req: IRTPatientInstanceBulkRequest, db: Session = Depends(get_db)):
        """IRT患者インスタンスを一括登録"""
        service = IRTPatientInstanceService(db)
        created = service.bulk_create_instances(req.instances)
        return {"created": len(created)}

    @app.get("/v1/irt/scenario-matrix")
    async def get_irt_scenario_matrix(catalog_version: Optional[int] = None, db: Session = Depends(get_db)):
        """シナリオ×項目マトリクスを取得"""
        service = IRTPatientInstanceService(db)
        matrix = service.get_scenario_matrix(catalog_version=catalog_version)
        return matrix

    @app.put("/v1/irt/item-types/{item_id}")
    async def update_irt_item_type(item_id: int, req: dict, db: Session = Depends(get_db)):
        """IRT項目タイプを更新"""
        service = IRTItemTypeService(db)
        it = service.update_item_type(item_id, **req)
        if not it:
            raise HTTPException(status_code=404, detail="Item type not found")
        return IRTItemTypeResponse(
            id=it.id, catalog_version=it.catalog_version, code=it.code,
            category=it.category, name_ja=it.name_ja, name_en=it.name_en,
            description=it.description, investigation_phase=it.investigation_phase,
            pdf_priority=it.pdf_priority, investigation_direction=it.investigation_direction,
            frequency=it.frequency, intensity=it.intensity, status=it.status,
            created_at=it.created_at
        )

    @app.delete("/v1/irt/item-types/{item_id}")
    async def delete_irt_item_type(item_id: int, db: Session = Depends(get_db)):
        """IRT項目タイプを削除"""
        service = IRTItemTypeService(db)
        if not service.delete_item_type(item_id):
            raise HTTPException(status_code=404, detail="Item type not found")
        return {"deleted": True}

    @app.put("/v1/irt/patient-instances/{instance_id}")
    async def update_irt_patient_instance(instance_id: int, req: dict, db: Session = Depends(get_db)):
        """IRT患者インスタンスを更新"""
        service = IRTPatientInstanceService(db)
        inst = service.update_instance(instance_id, **req)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        return IRTPatientInstanceResponse(
            id=inst.id, catalog_version=inst.catalog_version, patient_id=inst.patient_id,
            item_type_code=inst.item_type_code, instance_number=inst.instance_number,
            date=inst.date, description=inst.description,
            investigation_direction_override=inst.investigation_direction_override,
            scene_category=inst.scene_category,
            density_closed=inst.density_closed, density_crowded=inst.density_crowded,
            density_close_contact=inst.density_close_contact,
            related_patient_ids=inst.related_patient_ids,
            is_detectable=inst.is_detectable, notes=inst.notes,
            created_at=inst.created_at
        )

    @app.delete("/v1/irt/patient-instances/{instance_id}")
    async def delete_irt_patient_instance(instance_id: int, db: Session = Depends(get_db)):
        """IRT患者インスタンスを削除"""
        service = IRTPatientInstanceService(db)
        if not service.delete_instance(instance_id):
            raise HTTPException(status_code=404, detail="Instance not found")
        return {"deleted": True}

    # --- IRT Judgment API ---

    async def _execute_irt_judgment(session_id: str, db: Session):
        """セッションの対話ログからIRTインスタンスの正誤を一括判定する"""

        # 1. セッション情報取得
        session_record = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
        if not session_record:
            raise HTTPException(status_code=404, detail="Session not found")
        # statusチェック緩和: completedでなくてもchat_logsがあれば許可（バッチ実行対応）
        if session_record.status != 'completed':
            has_logs = db.query(modelDatabase.ChatLog).filter(
                modelDatabase.ChatLog.session_id == session_id,
                modelDatabase.ChatLog.sender.in_(["User", "Assistant"]),
                modelDatabase.ChatLog.is_initial_message == False
            ).first()
            if not has_logs:
                raise HTTPException(status_code=400, detail="Session is not completed yet and has no chat logs")

        patient_id = session_record.patient_id
        if not patient_id:
            raise HTTPException(status_code=400, detail="Session has no patient_id")

        # 2. 対話ログ取得（保健師・患者の発言のみ）
        chat_logs = db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id,
            modelDatabase.ChatLog.sender.in_(["User", "Assistant"]),
            modelDatabase.ChatLog.is_initial_message == False
        ).order_by(modelDatabase.ChatLog.created_at).all()

        if not chat_logs:
            raise HTTPException(status_code=400, detail="No chat logs found for this session")

        conversation_history = "\n".join([
            f"{log.ai_role or log.user_role}: {log.message}"
            for log in chat_logs
            if log.message and not log.message.startswith("Debriefing Data:")
        ])

        # 3. IRTインスタンス取得
        instance_service = IRTPatientInstanceService(db)
        instances = instance_service.get_instances_for_patient(patient_id)
        if not instances:
            raise HTTPException(status_code=400, detail=f"No IRT instances found for patient {patient_id}")

        # is_detectable=True のインスタンスのみ判定対象
        detectable_instances = [inst for inst in instances if inst.is_detectable]
        if not detectable_instances:
            raise HTTPException(status_code=400, detail="No detectable IRT instances for this patient")

        instances_text = "\n".join([
            f"- ID:{inst.id} [{inst.item_type_code}] {inst.description or ''}"
            for inst in detectable_instances
        ])

        # 4. 判定用プロンプト取得
        prompt_db = modelDatabase.PromptSessionLocal()
        try:
            prompt_service = PromptTemplateService(prompt_db)
            irt_eval_template = prompt_service.get_active_template('evaluator')
        finally:
            prompt_db.close()

        if not irt_eval_template:
            raise RuntimeError("評価者プロンプトがDBに登録されていません。プロンプト管理画面から登録してください。")

        base_prompt = irt_eval_template.prompt_text

        full_prompt = (
            f"{base_prompt}\n\n"
            f"【判定対象のIRT項目一覧】\n{instances_text}\n\n"
            f"【対話履歴】\n{conversation_history}\n\n"
            f"上記の対話履歴を分析し、各IRT項目について submit_irt_judgments 関数を呼び出して判定結果を提出してください。"
        )

        # 5. Function Calling ツール定義
        irt_judgment_tool = {
            "type": "function",
            "name": "submit_irt_judgments",
            "description": "対話ログに基づき、各IRT項目が正しく聴取されたかの判定結果を提出する",
            "parameters": {
                "type": "object",
                "properties": {
                    "judgments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "instance_id": {"type": "integer", "description": "IRT項目インスタンスのID"},
                                "is_correct": {"type": "boolean", "description": "正しく聴取されたか"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "確信度"},
                                "reasoning": {"type": "string", "description": "判定の根拠"}
                            },
                            "required": ["instance_id", "is_correct", "confidence", "reasoning"]
                        }
                    }
                },
                "required": ["judgments"]
            }
        }

        # 6. LLM呼び出し（専用スレッド）
        try:
            with open("assistants.json", "r") as f:
                assistants = json.load(f)
            if len(assistants) < 3:
                raise HTTPException(status_code=500, detail="Evaluator assistant ID not found in assistants.json")
            evaluator_assistant_id = assistants[2]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load assistant config: {e}")

        judgment_thread_id = None
        try:
            judgment_thread_id = await oaw.create_thread()
            logger.info(f"Created IRT judgment thread: {judgment_thread_id}")

            judgment_assistant = AssistantDef(
                user_id=ai_get_id(),
                role="評価者",
                assistant_id=evaluator_assistant_id,
                thread_id=judgment_thread_id
            )

            # プロンプトを分割送信
            prompt_chunks = role_provider._split_text_for_prompt(full_prompt, 2000)
            logger.info(f"Split IRT judgment prompt into {len(prompt_chunks)} chunks")

            for i, chunk in enumerate(prompt_chunks):
                await oaw.add_message_to_thread(judgment_assistant.thread_id, chunk)
                logger.info(f"Sent IRT judgment prompt chunk {i+1}/{len(prompt_chunks)}")

            final_instruction = "上記の情報を分析し、submit_irt_judgments 関数を呼び出して全IRT項目の判定結果を提出してください。"
            response_text, tool_call = await oaw.send_message(
                judgment_assistant,
                final_instruction,
                tools=[irt_judgment_tool],
                tool_choice="required",
                max_retries=5
            )

            if not tool_call or tool_call.name != "submit_irt_judgments":
                raise HTTPException(status_code=500, detail="LLM did not return expected tool call")

            result = json.loads(tool_call.arguments)
            llm_judgments = result.get("judgments", [])
            logger.info(f"LLM returned {len(llm_judgments)} judgments for session {session_id}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"IRT judgment LLM call failed: {e}")
            raise HTTPException(status_code=500, detail=f"LLM judgment failed: {e}")
        finally:
            if judgment_thread_id:
                try:
                    await oaw.delete_thread_by_id(judgment_thread_id)
                    logger.info(f"Deleted IRT judgment thread: {judgment_thread_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete IRT judgment thread: {e}")

        # 7. 既存の判定を削除して再判定
        judgment_service = IRTResponseJudgmentService(db)
        deleted = judgment_service.delete_judgments_for_session(session_id)
        if deleted > 0:
            logger.info(f"Deleted {deleted} existing judgments for session {session_id}")

        # 8. 判定結果をDBに保存
        valid_instance_ids = {inst.id for inst in detectable_instances}
        db_judgments = []
        for j in llm_judgments:
            if j.get("instance_id") not in valid_instance_ids:
                logger.warning(f"Skipping unknown instance_id: {j.get('instance_id')}")
                continue
            db_judgments.append({
                "session_id": session_id,
                "instance_id": j["instance_id"],
                "is_correct": j["is_correct"],
                "judgment_method": "ai",
                "confidence": j.get("confidence"),
                "notes": j.get("reasoning"),
            })

        saved = judgment_service.bulk_create_judgments(db_judgments)
        logger.info(f"Saved {len(saved)} IRT judgments for session {session_id}")

        return saved

    @app.post("/v1/irt/judgments/evaluate/{session_id}")
    async def evaluate_irt_judgments(session_id: str, db: Session = Depends(get_db)):
        """セッションの対話ログからIRT正誤判定を実行"""
        results = await _execute_irt_judgment(session_id, db)
        return {
            "session_id": session_id,
            "judged_count": len(results),
            "judgments": [
                IRTResponseJudgmentResponse(
                    id=j.id, session_id=j.session_id, instance_id=j.instance_id,
                    is_correct=j.is_correct, judgment_method=j.judgment_method,
                    confidence=j.confidence, evidence_message_ids=j.evidence_message_ids,
                    notes=j.notes, judged_at=j.judged_at
                ) for j in results
            ]
        }

    @app.get("/v1/irt/judgments/session/{session_id}")
    async def get_irt_judgments_for_session(session_id: str, db: Session = Depends(get_db)):
        """セッションのIRT判定結果を取得"""
        service = IRTResponseJudgmentService(db)
        judgments = service.get_judgments_for_session(session_id)
        return [
            IRTResponseJudgmentResponse(
                id=j.id, session_id=j.session_id, instance_id=j.instance_id,
                is_correct=j.is_correct, judgment_method=j.judgment_method,
                confidence=j.confidence, evidence_message_ids=j.evidence_message_ids,
                notes=j.notes, judged_at=j.judged_at
            ) for j in judgments
        ]

    @app.get("/v1/irt/judgments/instance/{instance_id}")
    async def get_irt_judgments_for_instance(instance_id: int, db: Session = Depends(get_db)):
        """インスタンスの全セッション判定結果を取得"""
        service = IRTResponseJudgmentService(db)
        judgments = service.get_judgments_for_instance(instance_id)
        return [
            IRTResponseJudgmentResponse(
                id=j.id, session_id=j.session_id, instance_id=j.instance_id,
                is_correct=j.is_correct, judgment_method=j.judgment_method,
                confidence=j.confidence, evidence_message_ids=j.evidence_message_ids,
                notes=j.notes, judged_at=j.judged_at
            ) for j in judgments
        ]

    @app.get("/v1/irt/judgments/patient/{patient_id}")
    async def get_irt_patient_stats(patient_id: str, db: Session = Depends(get_db)):
        """患者ID別のIRT判定統計を取得"""
        from collections import defaultdict

        inst_service = IRTPatientInstanceService(db)
        instances = inst_service.get_instances_for_patient(patient_id)
        if not instances:
            return PatientStatsResponse(
                patient_id=patient_id, total_sessions=0,
                sessions=[], item_stats=[], category_stats=[]
            )

        instance_ids = [inst.id for inst in instances]

        judg_service = IRTResponseJudgmentService(db)
        all_judgments = judg_service.get_judgments_by_instance_ids(instance_ids)

        # グルーピング
        judgments_by_instance = defaultdict(list)
        judgments_by_session = defaultdict(list)
        session_ids = set()
        for j in all_judgments:
            judgments_by_instance[j.instance_id].append(j)
            judgments_by_session[j.session_id].append(j)
            session_ids.add(j.session_id)

        # セッションメタデータ取得
        session_map = {}
        if session_ids:
            session_records = db.query(SessionModel).filter(
                SessionModel.session_id.in_(list(session_ids))
            ).all()
            session_map = {s.session_id: s for s in session_records}

        # セッション別統計
        sessions_list = []
        for sid in sorted(session_ids):
            sj = judgments_by_session[sid]
            sr = session_map.get(sid)
            correct = sum(1 for j in sj if j.is_correct)
            total = len(sj)
            sessions_list.append(PatientSessionStat(
                session_id=sid,
                created_at=sr.created_at if sr else None,
                nurse_model=sr.interviewer_model if sr else None,
                patient_model=sr.patient_model if sr else None,
                correct_count=correct,
                total_count=total,
                accuracy=correct / total if total > 0 else 0.0
            ))

        # 項目別統計
        item_stats = []
        category_totals = defaultdict(lambda: {"instances": 0, "acc_sum": 0.0, "count": 0})
        for inst in instances:
            ij = judgments_by_instance.get(inst.id, [])
            correct = sum(1 for j in ij if j.is_correct)
            total = len(ij)
            accuracy = correct / total if total > 0 else 0.0

            item_stats.append(PatientItemStat(
                instance_id=inst.id,
                item_type_code=inst.item_type_code,
                instance_number=inst.instance_number,
                description=inst.description,
                is_detectable=inst.is_detectable,
                total_judgments=total,
                correct_count=correct,
                accuracy=accuracy,
                sessions=[
                    PatientItemJudgmentDetail(
                        session_id=j.session_id,
                        is_correct=j.is_correct,
                        confidence=j.confidence,
                        notes=j.notes
                    ) for j in ij
                ]
            ))

            cat = inst.item_type_code.split("-")[0]
            category_totals[cat]["instances"] += 1
            if total > 0:
                category_totals[cat]["acc_sum"] += accuracy
                category_totals[cat]["count"] += 1

        # カテゴリ別統計
        category_stats = [
            PatientCategoryStat(
                category=cat,
                total_instances=data["instances"],
                avg_accuracy=data["acc_sum"] / data["count"] if data["count"] > 0 else 0.0
            )
            for cat, data in sorted(category_totals.items())
        ]

        return PatientStatsResponse(
            patient_id=patient_id,
            total_sessions=len(session_ids),
            sessions=sessions_list,
            item_stats=item_stats,
            category_stats=category_stats
        )

    # --- IRT Batch API ---

    class BatchStartRequest(BaseModel):
        patient_ids: List[str]
        runs_per_patient: int = 1
        concurrency: int = 2
        nurse_model: str = "gpt-4.1"
        patient_model: str = "gpt-4.1"
        evaluator_model: str = "gpt-4.1"
        patient_prompt_version: Optional[int] = None
        interviewer_prompt_version: Optional[int] = None
        evaluator_prompt_version: Optional[int] = None

    @app.post("/v1/irt/batch/start")
    async def start_irt_batch(req: BatchStartRequest):
        """ヘッドレスバッチ実行を開始"""
        if not req.patient_ids:
            raise HTTPException(status_code=400, detail="patient_ids is required")
        if req.runs_per_patient < 1:
            raise HTTPException(status_code=400, detail="runs_per_patient must be >= 1")
        if req.concurrency < 1:
            raise HTTPException(status_code=400, detail="concurrency must be >= 1")

        batch_id = await batch_runner.start_batch(
            req.patient_ids, req.runs_per_patient, req.concurrency,
            nurse_model=req.nurse_model,
            patient_model=req.patient_model,
            evaluator_model=req.evaluator_model,
            patient_prompt_version=req.patient_prompt_version,
            interviewer_prompt_version=req.interviewer_prompt_version,
            evaluator_prompt_version=req.evaluator_prompt_version,
        )
        total = len(req.patient_ids) * req.runs_per_patient
        logger.info(f"IRT batch started: batch_id={batch_id} total={total} models=nurse:{req.nurse_model}/patient:{req.patient_model}/eval:{req.evaluator_model} prompt_ver=patient:{req.patient_prompt_version}/interviewer:{req.interviewer_prompt_version}/evaluator:{req.evaluator_prompt_version}")
        return {"batch_id": batch_id, "total_tasks": total}

    @app.get("/v1/irt/batch/status/{batch_id}")
    async def get_irt_batch_status(batch_id: str):
        """バッチ実行状態を取得"""
        status = batch_runner.get_status(batch_id)
        if not status:
            raise HTTPException(status_code=404, detail="Batch not found")
        return status

    @app.post("/v1/irt/batch/stop/{batch_id}")
    async def stop_irt_batch(batch_id: str):
        """バッチ実行を停止"""
        stopped = batch_runner.stop_batch(batch_id)
        if not stopped:
            raise HTTPException(status_code=404, detail="Batch not found")
        return {"stopped": True}

    @app.post("/v1")
    async def post_request(req: RegistrationRequest, db: Session = Depends(get_db)):
        if req.msg_type != MsgType.RegistrationRequest.name:
            raise HTTPException(status_code=406, detail="Invalid message type")
        
        user_id = ai_get_id()
        session_id = str(uuid.uuid4())
        users_waiting[user_id] = UserDef(
            user_id=user_id, user_name=req.user_name, role=req.user_role,
            status=Status.Registered.name, target_patient_id=req.target_patient_id,
            session_id=session_id
        )
        return RegistrationAccepted(user_id=user_id, session_id=session_id)

    @app.websocket("/v1/ws/{user_id}")
    async def websocket_endpoint(user_id: str, ws: WebSocket, db: Session = Depends(get_db)):
        if user_id not in users_waiting:
            await ws.close(code=1008)
            return

        await ws.accept()
        user = users_waiting[user_id]
        user.ws = ws
        user.status = Status.Prepared.name

        try:
            # Case 1: Reconnecting to a session active in memory
            active_session = users_session.get(user.session_id)
            if active_session:
                logger.info(f"Reconnecting user {user.user_id} to active session {user.session_id}")
                # Update WebSocket object
                for i, u in enumerate(active_session.users):
                    if isinstance(u, UserDef):
                        active_session.users[i].ws = ws
                        break
                # History is already in memory, so just start the handler
                await _session_handler(user, db, logger, oaw, role_provider)
                return

            # Case 2: Restoring a session from DB (e.g., after server restart)
            db_session = db.query(SessionModel).filter(SessionModel.session_id == user.session_id).first()
            if db_session and db_session.status == 'active':
                logger.info(f"No active session in memory for {user.session_id}. Rebuilding from DB.")
                
                # 傍聴者の場合はセッション復元をサポートしない
                if user.role == "傍聴者":
                    logger.warning(f"Session restoration is not supported for observer role. Closing connection for user {user.user_id}")
                    await user.ws.close(code=1000, reason="Session restoration not supported for observer role")
                    return
                
                assistant = _find_peer_ai(user)
                if assistant:
                    assistant.thread_id = db_session.thread_id
                    history = History(assistant={"role": assistant.role, "assistant_id": assistant.assistant_id})
                    active_session = APISession(users=[user, assistant], history=history, session_id=user.session_id)
                    
                    # 会話終了検出器を初期化
                    try:
                        active_session.conversation_end_detector = ConversationEndDetector(oaw)
                        await active_session.conversation_end_detector.initialize()
                        logger.info("Conversation end detector initialized for restored session")
                    except Exception as e:
                        logger.warning(f"Failed to initialize conversation end detector for restored session: {e}")
                    
                    users_session[user.session_id] = active_session

                    # Restore history from DB
                    history_logs = db.query(modelDatabase.ChatLog).filter(
                        modelDatabase.ChatLog.session_id == active_session.session_id,
                        modelDatabase.ChatLog.sender != 'System'
                    ).order_by(modelDatabase.ChatLog.created_at.asc()).all()

                    for log in history_logs:
                        user_role = user.role
                        assistant_role = "患者" if user_role == "保健師" else "保健師"
                        role = user_role if log.sender == 'User' else assistant_role
                        active_session.history.history.append(MessageInfo(role=role, text=log.message))
                    
                    logger.info(f"Restored {len(history_logs)} messages to server-side session history for session {user.session_id}.")
                    await _session_handler(user, db, logger, oaw, role_provider)
                    return

            # Case 3: Creating a new session
            logger.info(f"Creating a new session for user {user.user_id}")
            peer = _find_peer_human(user)
            if peer:
                session_id = user.session_id or ai_get_id() # Fallback for safety
                session = APISession(users=[user, peer], history=History(), session_id=session_id)
                
                # 会話終了検出器を初期化（人間同士の場合）
                try:
                    session.conversation_end_detector = ConversationEndDetector(oaw)
                    await session.conversation_end_detector.initialize()
                    logger.info("Conversation end detector initialized for human-to-human session")
                except Exception as e:
                    logger.warning(f"Failed to initialize conversation end detector for human session: {e}")
                
                users_session[session_id] = session
                del users_waiting[user.user_id]
                del users_waiting[peer.user_id]
                
                await peer.ws.send_json(Established(session_id=session_id).dict())
                await user.ws.send_json(Established(session_id=session_id).dict())
                await _session_handler(user, db, logger, oaw, role_provider)
            else:
                assistant = _find_peer_ai(user)
                if assistant:
                    session_id = user.session_id
                    if not session_id:
                        logger.error(f"Session ID is missing for user {user.user_id}. Cannot establish session.")
                        await user.ws.close(code=1011, reason="Internal server error: session_id missing")
                        return

                    # Check if session already exists in the database
                    db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()

                    if not db_session:
                        # Create a new session record in the database only if it doesn't exist
                        logger.info(f"Creating session record for session_id: {session_id}")
                        
                        # 現在のプロンプトバージョンを取得
                        prompt_versions = get_current_prompt_versions(db)
                        
                        # モデル名を決定（人間が担当しない役割のみ）
                        # まず、セッションに参加するAssistantを特定
                        assistant = _find_peer_ai(user)
                        logger.info(f"Creating session for user role: {user.role}, assistant found: {assistant is not None}")
                        if assistant:
                            logger.info(f"Assistant details: role={assistant.role}, assistant_id={assistant.assistant_id}")
                        
                        patient_model = None
                        interviewer_model = None
                        evaluator_model = None
                        
                        if user.role == "患者":
                            # 患者が人間の場合、保健師と評価者はAI
                            logger.info("User is patient, getting interviewer model info")
                            try:
                                interviewer_model = await get_assistant_model_info(assistant.assistant_id if assistant else None, oaw)
                            except Exception as e:
                                logger.error(f"Failed to get interviewer model info: {e}")
                                interviewer_model = "UNKNOWN_MODEL"
                            # 評価者AIのモデル情報も取得
                            try:
                                with open("assistants.json", "r") as f:
                                    assistants = json.load(f)
                                if len(assistants) >= 3:
                                    evaluator_assistant_id = assistants[2]
                                    evaluator_model = await get_assistant_model_info(evaluator_assistant_id, oaw)
                                else:
                                    evaluator_model = "EVALUATOR_CONFIG_ERROR"
                            except Exception as e:
                                logger.error(f"Failed to get evaluator model info: {e}")
                                evaluator_model = "EVALUATOR_ERROR"
                            logger.info(f"Set interviewer_model={interviewer_model}, evaluator_model={evaluator_model}")
                        elif user.role == "保健師":
                            # 保健師が人間の場合、患者と評価者はAI
                            logger.info("User is interviewer, getting patient model info")
                            try:
                                patient_model = await get_assistant_model_info(assistant.assistant_id if assistant else None, oaw)
                            except Exception as e:
                                logger.error(f"Failed to get patient model info: {e}")
                                patient_model = "UNKNOWN_MODEL"
                            # 評価者AIのモデル情報も取得
                            try:
                                with open("assistants.json", "r") as f:
                                    assistants = json.load(f)
                                if len(assistants) >= 3:
                                    evaluator_assistant_id = assistants[2]
                                    evaluator_model = await get_assistant_model_info(evaluator_assistant_id, oaw)
                                else:
                                    evaluator_model = "EVALUATOR_CONFIG_ERROR"
                            except Exception as e:
                                logger.error(f"Failed to get evaluator model info: {e}")
                                evaluator_model = "EVALUATOR_ERROR"
                            logger.info(f"Set patient_model={patient_model}, evaluator_model={evaluator_model}")
                        elif user.role == "評価者":
                            # 評価者が人間の場合、患者と保健師はAI
                            logger.info("User is evaluator, getting model info for patient and interviewer")
                            try:
                                with open("assistants.json", "r") as f:
                                    assistants = json.load(f)
                                if len(assistants) >= 2:
                                    patient_assistant_id = assistants[0]
                                    interviewer_assistant_id = assistants[1]
                                    patient_model = await get_assistant_model_info(patient_assistant_id, oaw)
                                    interviewer_model = await get_assistant_model_info(interviewer_assistant_id, oaw)
                                else:
                                    patient_model = "PATIENT_CONFIG_ERROR"
                                    interviewer_model = "INTERVIEWER_CONFIG_ERROR"
                            except Exception as e:
                                logger.error(f"Failed to get model info for evaluator session: {e}")
                                patient_model = "PATIENT_ERROR"
                                interviewer_model = "INTERVIEWER_ERROR"
                            logger.info(f"Set patient_model={patient_model}, interviewer_model={interviewer_model}")
                        
                        # バージョンも同様に、人間が担当しない役割のみ記録
                        patient_version = None if user.role == "患者" else prompt_versions.get('patient_version')
                        interviewer_version = None if user.role == "保健師" else prompt_versions.get('interviewer_version')
                        evaluator_version = None if user.role == "評価者" else prompt_versions.get('evaluator_version')
                        
                        logger.info(f"Final session data - Models: patient={patient_model}, interviewer={interviewer_model}, evaluator={evaluator_model}")
                        logger.info(f"Final session data - Versions: patient={patient_version}, interviewer={interviewer_version}, evaluator={evaluator_version}")
                        
                        db_session = SessionModel(
                            session_id=session_id,
                            user_name=user.user_name,
                            user_role=user.role,
                            patient_id=user.target_patient_id if user.role in ["保健師", "傍聴者"] else None,
                            status='active',
                            patient_version=patient_version,
                            interviewer_version=interviewer_version,
                            evaluator_version=evaluator_version,
                            patient_model=patient_model,
                            interviewer_model=interviewer_model,
                            evaluator_model=evaluator_model
                        )
                        db.add(db_session)
                        db.commit()
                        db.refresh(db_session)

                    # Reuse or create thread_id and interview_date
                    interview_date_str = db_session.interview_date
                    if db_session.thread_id:
                        assistant.thread_id = db_session.thread_id
                        logger.info(f"Reusing existing thread_id: {assistant.thread_id}")
                        prompt_needed = False
                    else:
                        assistant.thread_id = await oaw.create_thread()
                        db_session.thread_id = assistant.thread_id
                        # interview_date is set below, so commit together
                        prompt_needed = True

                    history = History(assistant={"role": assistant.role, "assistant_id": assistant.assistant_id})
                    session = APISession(users=[user, assistant], history=history, session_id=session_id)
                    
                    # 会話終了検出器を初期化（人間とAIの場合）
                    try:
                        session.conversation_end_detector = ConversationEndDetector(oaw)
                        await session.conversation_end_detector.initialize()
                        logger.info("Conversation end detector initialized for human-AI session")
                    except Exception as e:
                        logger.warning(f"Failed to initialize conversation end detector for human-AI session: {e}")
                    
                    users_session[session_id] = session
                    del users_waiting[user.user_id]

                    if assistant.role == "患者":
                        patient_id_for_ai = user.target_patient_id or "1"
                        
                        if prompt_needed:
                            prompt_chunks, interview_date_str = role_provider.get_patient_prompt_chunks(patient_id_for_ai)
                            db_session.interview_date = interview_date_str
                            db.commit()
                            logger.info(f"Saved new interview_date: {interview_date_str}")
                        else:
                            prompt_chunks, _ = role_provider.get_patient_prompt_chunks(patient_id_for_ai, interview_date_str=db_session.interview_date)

                        if prompt_needed and interview_date_str:
                            for chunk in prompt_chunks:
                                await oaw.add_message_to_thread(assistant.thread_id, chunk)
                                history.history.append(MessageInfo(role="system", text=chunk))
                                await log_message(db, session_id, user.user_name, patient_id_for_ai, user.role, "System", chunk, logger)
                            
                            patient_details = role_provider.get_patient_details(patient_id_for_ai)
                            patient_name = patient_details.get("name", "名無し")
                            
                            # DBから患者AIの初期メッセージテンプレートを取得
                            try:
                                prompt_db = modelDatabase.PromptSessionLocal()
                                prompt_service = PromptTemplateService(prompt_db)
                                patient_template = prompt_service.get_active_template('patient')
                                prompt_db.close()
                                
                                if patient_template and patient_template.message_text:
                                    initial_bot_message = patient_template.message_text.replace('{patient_name}', patient_name)
                                else:
                                    # フォールバック
                                    initial_bot_message = f"私の名前は{patient_name}です。何でも聞いてください。"
                                    logger.warning("Patient template message not found in DB, using fallback message")
                            except Exception as e:
                                # エラー時のフォールバック
                                initial_bot_message = f"私の名前は{patient_name}です。何でも聞いてください。"
                                logger.error(f"Error loading patient template message: {e}")
                            history.history.append(MessageInfo(role="患者", text=initial_bot_message))
                            await log_message(db, session_id, "AI", patient_id_for_ai, user.role, "Assistant", initial_bot_message, logger, is_initial_message=True, ai_role="患者")
                        elif prompt_needed:
                             logger.error(f"Failed to generate prompt for patient ID {patient_id_for_ai}")

                    elif assistant.role == "保健師":
                        if prompt_needed:
                            # 患者データから面接日を取得
                            patient_id_for_ai = user.target_patient_id or "1"
                            _, interview_date_str = role_provider.get_patient_prompt_chunks(patient_id_for_ai)

                            db_session.interview_date = interview_date_str
                            db.commit()

                            prompt_chunks, initial_bot_message = role_provider.get_interviewer_prompt_chunks(interview_date_str)
                            for chunk in prompt_chunks:
                                await oaw.add_message_to_thread(assistant.thread_id, chunk)
                                history.history.append(MessageInfo(role="system", text=chunk))
                                await log_message(db, session_id, user.user_name, "N/A", user.role, "System", chunk, logger)
                            
                            # 保健師AIの初期メッセージを会話ログに含める
                            history.history.append(MessageInfo(role="保健師", text=initial_bot_message))
                            await log_message(db, session_id, "AI", assistant.assistant_id, user.role, "Assistant", initial_bot_message, logger, is_initial_message=False, ai_role="保健師")
                            await user.ws.send_json(MessageForwarded(session_id=session_id, user_msg=initial_bot_message).dict())

                    final_interview_date = db_session.interview_date or db_session.created_at.strftime("%Y年%m月%d日")
                    await user.ws.send_json(Established(session_id=session_id, interview_date=final_interview_date).dict())
                    await _session_handler(user, db, logger, oaw, role_provider)
                elif user.role == "傍聴者":
                    # 傍聴者の場合はAI同士の対話を開始
                    session_id = user.session_id
                    if not session_id:
                        logger.error(f"Session ID is missing for observer {user.user_id}. Cannot establish session.")
                        await user.ws.close(code=1011, reason="Internal server error: session_id missing")
                        return

                    # Check if session already exists in the database
                    db_session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()

                    if not db_session:
                        # Create a new session record for observer
                        logger.info(f"Creating observer session record for session_id: {session_id}")
                        
                        # 現在のプロンプトバージョンを取得
                        prompt_versions = get_current_prompt_versions(db)
                        
                        # 傍聴者の場合は全てのロールがAI
                        # 実際のAssistantモデル情報を取得
                        try:
                            # assistants.jsonから実際のAssistant IDを取得
                            with open("assistants.json", "r") as f:
                                assistants = json.load(f)
                            
                            if len(assistants) >= 3:
                                patient_assistant_id = assistants[0]  # 1番目: 患者AI
                                interviewer_assistant_id = assistants[1]  # 2番目: 保健師AI
                                evaluator_assistant_id = assistants[2]  # 3番目: 評価者AI
                                
                                # 各AIの実際のモデル情報を取得
                                patient_model = await get_assistant_model_info(patient_assistant_id, oaw)
                                interviewer_model = await get_assistant_model_info(interviewer_assistant_id, oaw)
                                evaluator_model = await get_assistant_model_info(evaluator_assistant_id, oaw)
                                
                                logger.info(f"Observer session models - patient: {patient_model}, interviewer: {interviewer_model}, evaluator: {evaluator_model}")
                            else:
                                logger.error("Not enough assistants defined in assistants.json for observer mode")
                                patient_model = "ASSISTANT_CONFIG_ERROR"
                                interviewer_model = "ASSISTANT_CONFIG_ERROR" 
                                evaluator_model = "ASSISTANT_CONFIG_ERROR"
                        except Exception as e:
                            logger.error(f"Failed to get model info for observer session: {e}")
                            patient_model = "MODEL_RETRIEVAL_ERROR"
                            interviewer_model = "MODEL_RETRIEVAL_ERROR"
                            evaluator_model = "MODEL_RETRIEVAL_ERROR"
                        
                        db_session = SessionModel(
                            session_id=session_id,
                            user_name=user.user_name,
                            user_role=user.role,
                            patient_id=user.target_patient_id,
                            status='active',
                            patient_version=prompt_versions.get('patient_version'),
                            interviewer_version=prompt_versions.get('interviewer_version'),
                            evaluator_version=prompt_versions.get('evaluator_version'),
                            patient_model=patient_model,
                            interviewer_model=interviewer_model,
                            evaluator_model=evaluator_model
                        )
                        db.add(db_session)
                        db.commit()
                        db.refresh(db_session)

                    # Create session with AI conversation manager
                    history = History()
                    session = APISession(users=[user], history=history, session_id=session_id)
                    
                    # 会話終了検出器を初期化（傍聴者の場合）
                    try:
                        session.conversation_end_detector = ConversationEndDetector(oaw)
                        await session.conversation_end_detector.initialize()
                        logger.info("Conversation end detector initialized for observer session")
                    except Exception as e:
                        logger.warning(f"Failed to initialize conversation end detector for observer session: {e}")
                    
                    # Initialize AI conversation manager
                    ai_manager = AIConversationManager(session, user, oaw, role_provider, db, logger)
                    session.ai_conversation_manager = ai_manager
                    
                    if not await ai_manager.initialize_ais():
                        logger.error(f"Failed to initialize AI conversation for observer {user.user_id}")
                        await user.ws.close(code=1011, reason="Failed to initialize AI conversation")
                        return
                    
                    # 面接日を計算してデータベースに保存（保健師ロールと同じロジック）
                    patient_id_for_ai = user.target_patient_id or "1"
                    prompt_chunks, interview_date_str = role_provider.get_patient_prompt_chunks(patient_id_for_ai)
                    db_session.interview_date = interview_date_str
                    db.commit()
                    
                    if not await ai_manager.setup_ai_prompts(interview_date_str):
                        logger.error(f"Failed to setup AI prompts for observer {user.user_id}")
                        await user.ws.close(code=1011, reason="Failed to setup AI prompts")
                        return
                    
                    users_session[session_id] = session
                    del users_waiting[user.user_id]

                    final_interview_date = db_session.interview_date or db_session.created_at.strftime("%Y年%m月%d日")
                    await user.ws.send_json(Established(session_id=session_id, interview_date=final_interview_date).dict())
                    
                    # Start AI conversation
                    await ai_manager.start_conversation()
                    
                    await _session_handler(user, db, logger, oaw, role_provider)
                else:
                    await user.ws.send_json(Prepared().dict())
                    await _session_handler(user, db, logger, oaw, role_provider)
        except WebSocketDisconnect:
            logger.debug(f"WS Exception: {user.user_id}")
        finally:
            if user_id in users_waiting: del users_waiting[user_id]
            session = _find_user_session(user_id)
            if session:
                for u in session.users:
                    if u.user_id != user_id and hasattr(u, 'ws') and u.ws:
                        await u.ws.close(code=1001)
                del users_session[session.session_id]

    async def _session_handler(user: UserDef, db: Session, logger, oaw: OpenAIAssistantWrapper = None, role_provider=None):
        session = _find_user_session(user.user_id)
        if not session: return

        try:
            while True:
                data = await user.ws.receive_json()
                msg_type = data.get("msg_type")

                if msg_type == MsgType.MessageSubmitted.name:
                    m = MessageSubmitted.model_validate(data)
                    await log_message(db, session.session_id, user.user_name, user.target_patient_id, user.role, "User", m.user_msg, logger, is_initial_message=False)
                    session.history.history.append(MessageInfo(role=user.role, text=m.user_msg))
                    
                    # 保健師ロールの場合、ユーザー（保健師）の発言後も会話終了検出を実行
                    if user.role == "保健師" and session.conversation_end_detector:
                        logger.info(f"Processing end detection after nurse user message for session {session.session_id}")
                        try:
                            # ユーザーメッセージを検出器に追加
                            await session.conversation_end_detector.add_conversation_message(m.user_msg, user.role)
                            logger.info(f"Added user message to end detector: [{user.role}] {m.user_msg[:50]}...")
                            
                            # 会話継続直後は検出をスキップ
                            if session.skip_next_end_detection:
                                session.skip_next_end_detection = False  # フラグをリセット
                                logger.info("Skipping conversation end detection (continue request)")
                            else:
                                # 会話終了を検出
                                logger.info("Executing conversation end detection after nurse user message...")
                                end_detection_result = await session.conversation_end_detector.check_conversation_end()
                                logger.info(f"End detection result: {end_detection_result}")
                                
                                if end_detection_result and end_detection_result.get("detected"):
                                    confidence = end_detection_result.get("confidence", 0.0)
                                    reason = end_detection_result.get("reason", "")
                                    
                                    # 確信度が0.95以上の場合に会話終了として扱う
                                    confidence_threshold = 0.95
                                    if confidence >= confidence_threshold:
                                        logger.info(f"Conversation end detected by specialist AI (confidence: {confidence:.2f}): {reason}")
                                        
                                        # WebSocketで会話終了選択肢を通知
                                        await user.ws.send_json(ConversationEndChoices(session_id=session.session_id).model_dump())
                                        # 会話終了が検出された場合、AI応答は生成しない
                                        continue
                                    else:
                                        logger.info(f"Conversation end detected but confidence too low (confidence: {confidence:.2f} < {confidence_threshold}): {reason}")
                                else:
                                    logger.info("No conversation end detected after nurse message, continuing...")
                        except Exception as e:
                            logger.error(f"Error during conversation end detection after user message: {e}")
                            # 検出エラーは会話を止めない

                    for peer in session.users:
                        if peer.user_id == user.user_id: continue
                        
                        if isinstance(peer, AssistantDef) and oaw:
                            try:
                                # ロールに応じてFunction Callingを制御
                                tools_param = None # デフォルト（保健師ロール）
                                if user.role == "患者":
                                    tools_param = [] # 患者ロールの場合は無効化

                                response_msg, tool_call = await oaw.send_message(
                                    peer, m.user_msg, tools=tools_param, max_retries=3
                                )
                            except NotFoundError:
                                logger.warning(f"Thread {peer.thread_id} not found. Recreating thread...")
                                # スレッドを再作成し、DBとセッション情報を更新
                                new_thread_id = await oaw.create_thread()
                                peer.thread_id = new_thread_id
                                db_session = db.query(SessionModel).filter(SessionModel.session_id == session.session_id).first()
                                if db_session:
                                    db_session.thread_id = new_thread_id
                                    db.commit()
                                
                                # プロンプトを再注入する必要がある
                                if peer.role == "患者":
                                    patient_id_for_ai = user.target_patient_id or "1"
                                    prompt_chunks, _ = role_provider.get_patient_prompt_chunks(patient_id_for_ai, interview_date_str=db_session.interview_date if db_session else None)
                                    for chunk in prompt_chunks:
                                        await oaw.add_message_to_thread(peer.thread_id, chunk)
                                elif peer.role == "保健師":
                                    prompt_chunks, _ = role_provider.get_interviewer_prompt_chunks()
                                    for chunk in prompt_chunks:
                                        await oaw.add_message_to_thread(peer.thread_id, chunk)

                                logger.info(f"Re-sending message to new thread {new_thread_id}")
                                response_msg, tool_call = await oaw.send_message(peer, m.user_msg, max_retries=3)

                            if tool_call and tool_call.name == "end_conversation_and_start_debriefing":
                                # LLMが会話の終了を判断した場合、クライアントに通知して確認を促す
                                logger.info(f"Tool call detected: {tool_call.name}. Notifying client...")
                                await user.ws.send_json(ConversationEndChoices(session_id=session.session_id).model_dump())
                            elif response_msg:
                                if response_msg.startswith("FAILED:"):
                                    # エラー応答
                                    logger.error(f"AI response failed: {response_msg}")
                                    await user.ws.send_json(MessageRejected(session_id=session.session_id, reason=response_msg).dict())
                                else:
                                    # 通常のテキスト応答
                                    session.history.history.append(MessageInfo(role=peer.role, text=response_msg))
                                    await log_message(db, session.session_id, "AI", peer.assistant_id, user.role, "Assistant", response_msg, logger, is_initial_message=False, ai_role=peer.role)
                                    await user.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=response_msg).dict())
                                    
                                    # 会話終了検出処理（各メッセージ交換後）- 患者側の発言後のみ実行
                                    logger.info(f"Processing end detection for session {session.session_id}")
                                    if session.conversation_end_detector:
                                        logger.info(f"Conversation end detector found for session {session.session_id}")
                                        try:
                                            # AI応答を検出器に追加（常に履歴は蓄積する）
                                            await session.conversation_end_detector.add_conversation_message(response_msg, peer.role)
                                            logger.info(f"Added message to end detector: [{peer.role}] {response_msg[:50]}...")
                                            
                                            # ロールに応じて会話終了検出を実行
                                            should_detect = False
                                            detection_reason = ""
                                            
                                            if user.role == "保健師":
                                                # 保健師ロールの場合: 患者AIの発言後とユーザー（保健師）の発言後の両方で検出
                                                if peer.role == "患者":
                                                    should_detect = True
                                                    detection_reason = "patient AI response in nurse session"
                                                else:
                                                    logger.info(f"Skipping end detection - peer role is {peer.role}, expected 患者 for nurse session")
                                            elif user.role == "患者":
                                                # 患者ロールの場合: 患者の発言後のみ検出（従来通り）
                                                if peer.role == "患者":
                                                    should_detect = True
                                                    detection_reason = "patient response in patient session"
                                                else:
                                                    logger.info(f"Skipping end detection - waiting for patient response (current peer: {peer.role})")
                                            else:
                                                logger.info(f"Skipping end detection - unsupported user role: {user.role}")
                                            
                                            if should_detect:
                                                # 会話継続直後は検出をスキップ
                                                if session.skip_next_end_detection:
                                                    session.skip_next_end_detection = False  # フラグをリセット
                                                    logger.info("Skipping conversation end detection (continue request)")
                                                else:
                                                    # 会話終了を検出
                                                    logger.info(f"Executing conversation end detection after {detection_reason}...")
                                                    end_detection_result = await session.conversation_end_detector.check_conversation_end()
                                                    logger.info(f"End detection result: {end_detection_result}")
                                                    
                                                    if end_detection_result and end_detection_result.get("detected"):
                                                        confidence = end_detection_result.get("confidence", 0.0)
                                                        reason = end_detection_result.get("reason", "")
                                                        
                                                        # 確信度が0.95以上の場合に会話終了として扱う
                                                        confidence_threshold = 0.95
                                                        if confidence >= confidence_threshold:
                                                            logger.info(f"Conversation end detected by specialist AI (confidence: {confidence:.2f}): {reason}")
                                                            
                                                            # WebSocketで会話終了選択肢を通知
                                                            await user.ws.send_json(ConversationEndChoices(session_id=session.session_id).model_dump())
                                                        else:
                                                            logger.info(f"Conversation end detected but confidence too low (confidence: {confidence:.2f} < {confidence_threshold}): {reason}")
                                                    else:
                                                        logger.info("No conversation end detected, continuing...")
                                        except Exception as e:
                                            logger.error(f"Error during conversation end detection: {e}")
                                            # 検出エラーは会話を止めない
                                    else:
                                        logger.warning(f"No conversation end detector found for session {session.session_id}")
                        elif isinstance(peer, UserDef):
                            await log_message(db, session.session_id, peer.user_name, peer.target_patient_id, peer.role, "Assistant", m.user_msg, logger, is_initial_message=False)
                            await peer.ws.send_json(MessageForwarded(session_id=session.session_id, user_msg=m.user_msg).dict())

                elif msg_type == MsgType.DebriefingRequest.name:
                    m = DebriefingRequest.model_validate(data)
                    logger.info(f"DebriefingRequest received from user: {m.user_id}")
                    
                    # 傍聴者の場合はAI対話を確実に停止
                    if user.role == "傍聴者" and session.ai_conversation_manager:
                        await session.ai_conversation_manager.stop_conversation()
                        logger.info(f"AI conversation stopped for debriefing in session {session.session_id}")
                    
                    await _execute_debriefing(session, user, db, logger, oaw, role_provider)

                elif msg_type == MsgType.ContinueConversationRequest.name:
                    m = ContinueConversationRequest.model_validate(data)
                    logger.info(f"ContinueConversationRequest received from user: {m.user_id}")
                    
                    # 会話終了検知器のアクティブなrunをキャンセル
                    if session.conversation_end_detector:
                        try:
                            await session.conversation_end_detector.cancel_active_runs()
                            logger.info("Cancelled active runs for conversation end detector")
                        except Exception as e:
                            logger.error(f"Failed to cancel active runs for conversation end detector: {e}")
                    
                    # 次回の会話終了検知をスキップするフラグを設定
                    session.skip_next_end_detection = True
                    logger.info("Next conversation end detection will be skipped")
                    
                    if user.role == "傍聴者" and session.ai_conversation_manager:
                        # 傍聴者の場合はAI対話を継続
                        await session.ai_conversation_manager.handle_continue_conversation()
                    else:
                        # 通常の人間対AI対話の場合
                        peer_ai = next((p for p in session.users if isinstance(p, AssistantDef)), None)
                        if peer_ai and oaw:
                            cancelled = await oaw.cancel_run(peer_ai.thread_id)
                            if cancelled:
                                logger.info(f"Run cancelled for thread {peer_ai.thread_id}. Notifying client to continue.")
                                await user.ws.send_json(ConversationContinueAccepted(session_id=session.session_id).dict())
                            else:
                                logger.warning(f"Failed to cancel run for thread {peer_ai.thread_id}. Client might be stuck.")

                elif msg_type == MsgType.EndSessionRequest.name:
                    m = EndSessionRequest.model_validate(data)
                    await _save_history(session.session_id, session.history, logger)
                    
                    # Mark session as completed in the new table
                    db_session = db.query(SessionModel).filter(SessionModel.session_id == session.session_id).first()
                    if db_session:
                        db_session.status = 'completed'
                        db_session.completed_at = datetime.now()
                        db.commit()

                    # 傍聴者の場合はAI対話を停止
                    if user.role == "傍聴者" and session.ai_conversation_manager:
                        await session.ai_conversation_manager.cleanup()

                    for u in session.users:
                        if hasattr(u, 'ws') and u.ws:
                            reason = "EndSession request is accepted." if u.user_id == m.user_id else "Peer sent the end of session."
                            await u.ws.send_json(SessionTerminated(session_id=session.session_id, reason=reason).dict())
                            await u.ws.close()
                        if isinstance(u, AssistantDef) and oaw:
                            await oaw.delete_thread(u)
                    break
        except WebSocketDisconnect:
            logger.debug(f"WS Disconnect in session: {user.user_id}")
        except Exception as e:
            logger.error(f"Error in session handler: {e}")
        finally:
            if session.session_id in users_session:
                # 会話終了検出器のクリーンアップ
                if session.conversation_end_detector:
                    try:
                        await session.conversation_end_detector.cleanup()
                    except Exception as e:
                        logger.error(f"Error during conversation end detector cleanup: {e}")
                
                # 傍聴者の場合は AI対話を停止
                if user.role == "傍聴者" and session.ai_conversation_manager:
                    try:
                        await session.ai_conversation_manager.cleanup()
                    except Exception as e:
                        logger.error(f"Error during AI conversation cleanup: {e}")
                del users_session[session.session_id]

    # SPA fallback: serve index.html for non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Skip API routes
        if full_path.startswith("v1/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        
        # Try to serve the requested file
        file_path = f"dist/{full_path}"
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # For everything else (SPA routes), serve index.html
        if os.path.exists("dist/index.html"):
            return FileResponse("dist/index.html")
        
        raise HTTPException(status_code=404, detail="File not found")

    app.mount("/", StaticFiles(directory="dist", html=True), name="dist")
    return app
