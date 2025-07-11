from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import os

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
    
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # プロンプト管理用も同じDBを使用（共通DB）
    prompt_engine = engine
    PromptSessionLocal = SessionLocal

TABLE_SUFFIX = os.getenv("TABLE_SUFFIX", "")

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
