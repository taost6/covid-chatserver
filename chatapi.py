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
from modelDatabase import db_retry
from openai import NotFoundError
from openai_assistant import OpenAIAssistantWrapper
from ai_conversation_manager import AIConversationManager, get_id as ai_get_id

# Logger setup
logger = logging.getLogger(__name__)

class APISession(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    users: List[Union[UserDef, AssistantDef]]
    history: History
    session_id: str
    ai_conversation_manager: Optional[Any] = None

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
        return "gpt-4o"
    
    if not oaw:
        return "gpt-4o"
    
    try:
        assistant_info = await oaw.get_assistant_info(assistant_id)
        
        if not assistant_info:
            return "gpt-4o"
        
        model_name = assistant_info.get("model")
        if not model_name:
            return "gpt-4o"
        
        # 実際のモデル名を返す
        return model_name
        
    except Exception as e:
        return "gpt-4o"

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

    # Function Calling用のツール定義
    debriefing_tool = {
        "type": "function",
        "function": {
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
    }

    # 対話履歴を整形
    conversation_history = "\n".join([
        f"{msg.role}: {msg.text}" 
        for msg in session.history.history 
        if msg.role in ["保健師", "患者"]
    ])
    
    # 患者の初期設定情報を取得（評価者AIが正解を知るため）
    patient_setting_info = ""
    try:
        # 患者IDを特定
        patient_id = None
        for u in session.users:
            if hasattr(u, 'target_patient_id') and u.target_patient_id:
                patient_id = u.target_patient_id
                break
        
        if patient_id and role_provider:
            # 患者の詳細情報を取得
            patient_details = role_provider.get_patient_details(patient_id)
            if patient_details:
                # 面接日を特定（セッション履歴から取得）
                interview_date_str = None
                for msg in session.history.history:
                    if msg.role == "system" and "面接日：" in msg.text:
                        import re
                        match = re.search(r'面接日：(\d{4}-\d{2}-\d{2})', msg.text)
                        if match:
                            interview_date_str = match.group(1)
                            break
                
                # 患者プロンプトの全情報を取得（評価者が正解を知るため）
                prompt_chunks, calculated_interview_date = role_provider.get_patient_prompt_chunks(patient_id, interview_date_str)
                patient_setting_info = "\n".join(prompt_chunks)
                logger.info(f"Retrieved patient setting information for evaluation (patient_id: {patient_id})")
            else:
                logger.warning(f"Could not retrieve patient details for patient_id: {patient_id}")
        else:
            logger.warning("Could not determine patient_id for debriefing evaluation")
    except Exception as e:
        logger.error(f"Failed to retrieve patient setting information for evaluation: {e}")
        patient_setting_info = ""
    
    # DB から評価AIプロンプトを取得
    try:
        prompt_db = modelDatabase.PromptSessionLocal()
        prompt_service = PromptTemplateService(prompt_db)
        evaluator_template = prompt_service.get_active_template('evaluator')
        prompt_db.close()
        
        if evaluator_template:
            base_prompt = evaluator_template.prompt_text
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
    
    # Debriefing専用プロンプト（患者設定情報を含む）
    debriefing_prompt = base_prompt + "\n\n"
    
    if patient_setting_info:
        debriefing_prompt += f"【患者の設定情報（正解データ）】\n{patient_setting_info}\n\n"
    
    debriefing_prompt += f"【対話履歴】\n{conversation_history}\n\n"
    
    # 具体的な指示を追加
    debriefing_prompt += """
**評価時の注意点**:
1. 患者の設定情報と対話履歴を詳細に比較し、聞き出せなかった重要な情報を特定してください
2. missed_pointsでは、抽象的な表現ではなく具体的な事実を記述してください
3. 日付、時刻、場所名、人物名、行動内容などの具体的な詳細を含めてください
4. 感染経路調査や濃厚接触者特定の観点から重要度を判定してください

上記の指示に従って、詳細な評価レポートを作成してください。
"""

    try:
        # 評価を実行
        _, tool_call = await oaw.send_message(
            debriefing_assistant,
            debriefing_prompt,
            tools=[debriefing_tool],
            tool_choice={"type": "function", "function": {"name": "submit_debriefing_report"}}
        )

        debriefing_data = None
        if tool_call and tool_call.function.name == "submit_debriefing_report":
            try:
                args = json.loads(tool_call.function.arguments)
                debriefing_data = args
                logger.info("Successfully parsed debriefing report from specialist assistant.")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse debriefing tool call arguments: {e}")
                logger.error(f"Raw arguments: {tool_call.function.arguments}")
                debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: 評価データの解析エラー）"}
        else:
            logger.error(f"Debriefing failed. Expected tool call 'submit_debriefing_report' but got: {tool_call}")
            debriefing_data = {"error": "評価レポートの生成に失敗しました。（理由: AIが評価データを生成できませんでした）"}

    except Exception as e:
        logger.error(f"Error during debriefing execution: {e}")
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
    await user.ws.send_json(DebriefingResponse(session_id=session.session_id, debriefing_data=debriefing_data).dict())
    
    # ログに保存
    await log_message(db, session.session_id, "System", debriefing_assistant_id, "評価者", "System", f"Debriefing Data: {json.dumps(debriefing_data, ensure_ascii=False)}", logger)
    
    # チャットログにシステムメッセージとして評価レポートへのリンクを追加
    debriefing_link_message = f" 評価レポートが完成しました。[レポートを表示](/debriefing/{session.session_id})"
    await log_message(db, session.session_id, user.user_name, debriefing_assistant_id, "評価者", "System", debriefing_link_message, logger)


async def _execute_debriefing(session: APISession, user: UserDef, db: Session, logger, oaw: OpenAIAssistantWrapper, role_provider):
    """Debriefing処理を実行し、結果をクライアントに送信する"""
    # 新しい専用Assistantを使用したDebriefing処理に移行
    await _execute_debriefing_with_specialist(session, user, db, logger, oaw, role_provider)


# --- Main API Factory ---
def api(config):
    logger = config.logger
    oaw = OpenAIAssistantWrapper(config)
    role_provider = PatientRoleProvider(config)
    
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

    @app.get("/v1/patient/{patient_id}")
    async def get_patient_details(patient_id: str):
        if role_provider.df is None:
            raise HTTPException(status_code=503, detail="Patient data is not ready.")
        details = role_provider.get_patient_details(patient_id)
        if "error" in details:
            raise HTTPException(status_code=404, detail=details['error'])
        return details

    @app.get("/v1/session/{session_id}")
    @db_retry(max_retries=3, delay=1.0, backoff=2.0)
    def _get_session_from_db(db: Session, session_id: str):
        """データベースからセッション情報を取得（リトライ機能付き）"""
        return db.query(SessionModel).filter(
            SessionModel.session_id == session_id,
            SessionModel.status == 'active'
        ).first()

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

    @app.get("/v1/logs")
    @db_retry(max_retries=3, delay=1.0, backoff=2.0)
    def _get_sessions_from_db(db: Session):
        """データベースからセッション一覧を取得（リトライ機能付き）"""
        return db.query(SessionModel).order_by(
            desc(SessionModel.created_at)
        ).all()

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

    @app.get("/v1/logs/{session_id}")
    @db_retry(max_retries=3, delay=1.0, backoff=2.0)
    def _get_chat_logs_from_db(db: Session, session_id: str):
        """データベースからチャットログを取得（リトライ機能付き）"""
        return db.query(modelDatabase.ChatLog).filter(
            modelDatabase.ChatLog.session_id == session_id
        ).order_by(
            modelDatabase.ChatLog.created_at
        ).all()

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
                            interviewer_model = await get_assistant_model_info(assistant.assistant_id if assistant else None, oaw)
                            evaluator_model = "gpt-4o"  # 評価者は別途処理
                            logger.info(f"Set interviewer_model={interviewer_model}, evaluator_model={evaluator_model}")
                        elif user.role == "保健師":
                            # 保健師が人間の場合、患者と評価者はAI
                            logger.info("User is interviewer, getting patient model info")
                            patient_model = await get_assistant_model_info(assistant.assistant_id if assistant else None, oaw)
                            evaluator_model = "gpt-4o"  # 評価者は別途処理
                            logger.info(f"Set patient_model={patient_model}, evaluator_model={evaluator_model}")
                        elif user.role == "評価者":
                            # 評価者が人間の場合、患者と保健師はAI
                            logger.info("User is evaluator, using default models for patient and interviewer")
                            patient_model = "gpt-4o"  # 複数のAssistantが関わる場合は後で改善
                            interviewer_model = "gpt-4o"
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
                            # 患者の感染日/発症日に基づいて面接日を計算（共通メソッド使用）
                            patient_id_for_ai = user.target_patient_id or "1"
                            interview_date_str = role_provider.calculate_interview_date(patient_id_for_ai)
                            
                            db_session.interview_date = interview_date_str
                            db.commit()

                            prompt_chunks, initial_bot_message = role_provider.get_interviewer_prompt_chunks()
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
                            # 患者と保健師のAssistantを特定
                            # 傍聴者モードでは複数のAssistantが関わるため、一旦デフォルト値を使用
                            patient_model = "gpt-4o"  # 実際のAssistant情報の取得は複雑になるため、今回はデフォルト値
                            interviewer_model = "gpt-4o"
                            evaluator_model = "gpt-4o"
                        except Exception as e:
                            logger.error(f"Failed to get model info for observer session: {e}")
                            patient_model = "gpt-4o"
                            interviewer_model = "gpt-4o"
                            evaluator_model = "gpt-4o"
                        
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

                    for peer in session.users:
                        if peer.user_id == user.user_id: continue
                        
                        if isinstance(peer, AssistantDef) and oaw:
                            try:
                                # ロールに応じてFunction Callingを制御
                                tools_param = None # デフォルト（保健師ロール）
                                if user.role == "患者":
                                    tools_param = [] # 患者ロールの場合は無効化

                                response_msg, tool_call = await oaw.send_message(
                                    peer, m.user_msg, tools=tools_param
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
                                response_msg, tool_call = await oaw.send_message(peer, m.user_msg)

                            if tool_call and tool_call.function.name == "end_conversation_and_start_debriefing":
                                # LLMが会話の終了を判断した場合、クライアントに通知して確認を促す
                                logger.info(f"Tool call detected: {tool_call.function.name}. Notifying client...")
                                await user.ws.send_json(ToolCallDetected(session_id=session.session_id).dict())
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
