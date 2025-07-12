from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.exc import OperationalError, DisconnectionError
import os
import time
import logging
from functools import wraps

# 新しいSessionモデルをインポート
from modelSession import Base as SessionBase
from modelPrompt import Base as PromptBase

# これらはアプリケーション起動時に initialize_database() によって初期化されます
engine = None
SessionLocal = None
Base = declarative_base()

# プロンプト管理用（共通DB接続）
prompt_engine = None
PromptSessionLocal = None

def initialize_database(db_url: str):
    """データベースエンジンとセッションファクトリを初期化します。"""
    global engine, SessionLocal, prompt_engine, PromptSessionLocal
    if not db_url:
        raise ValueError("データベースURLが設定されていません。データベースを初期化できません。")
    
    # 接続プールとリトライ設定を強化
    engine = create_engine(
        db_url,
        # 接続プール設定
        pool_size=10,                    # 基本的な接続プールサイズ
        max_overflow=20,                 # プールが満杯時の追加接続数
        pool_timeout=30,                 # プールから接続を取得するまでの待機時間（秒）
        pool_recycle=3600,              # 接続を1時間で再作成（SSL切断対策）
        pool_pre_ping=True,             # 接続使用前にpingで確認（切断検出）
        
        # PostgreSQL固有の設定
        connect_args={
            "sslmode": "require",        # SSL接続を強制
            "connect_timeout": 10,       # 初期接続タイムアウト（秒）
            "application_name": "covid_chatserver",  # アプリケーション識別
        },
        
        # ログ設定（本番環境では無効化）
        echo=False
    )
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # プロンプト管理用も同じDBを使用（共通DB）
    prompt_engine = engine
    PromptSessionLocal = SessionLocal

TABLE_SUFFIX = os.getenv("TABLE_SUFFIX", "")

logger = logging.getLogger(__name__)

def db_retry(max_retries=3, delay=1.0, backoff=2.0):
    """
    データベース操作のリトライデコレータ
    SSL接続切断エラーや一時的な接続エラーに対して自動リトライを行う
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, DisconnectionError) as e:
                    last_exception = e
                    error_msg = str(e).lower()
                    
                    # SSL接続切断や接続エラーの場合のみリトライ
                    if any(keyword in error_msg for keyword in [
                        'ssl connection has been closed unexpectedly',
                        'connection was closed unexpectedly',
                        'server closed the connection unexpectedly',
                        'could not connect to server',
                        'connection timeout',
                        'connection refused'
                    ]):
                        if attempt < max_retries:
                            wait_time = delay * (backoff ** attempt)
                            logger.warning(
                                f"Database connection error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                                f"Retrying in {wait_time:.1f} seconds..."
                            )
                            time.sleep(wait_time)
                            continue
                    
                    # リトライ対象外のエラーまたは最大試行回数に達した場合
                    raise e
                except Exception as e:
                    # その他の例外はリトライしない
                    raise e
            
            # 最大試行回数に達した場合
            logger.error(f"Database operation failed after {max_retries + 1} attempts. Last error: {last_exception}")
            raise last_exception
        
        return wrapper
    return decorator

class ChatLog(Base):
    __tablename__ = f"chat_logs{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    user_name = Column(String)
    patient_id = Column(String, nullable=True)
    user_role = Column(String)
    sender = Column(String) # System, User, Assistant
    ai_role = Column(String, nullable=True) # 保健師, 患者 (for AI messages only)
    message = Column(Text)
    is_initial_message = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

def init_db():
    """データベーステーブルを作成します。"""
    if engine is None:
        raise RuntimeError("データベースが初期化されていません。先に initialize_database() を呼び出してください。")
    # 全てのモデルのテーブルを作成
    Base.metadata.create_all(bind=engine)
    SessionBase.metadata.create_all(bind=engine)
    PromptBase.metadata.create_all(bind=engine)
