from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import os

# これらはアプリケーション起動時に initialize_database() によって初期化されます
engine = None
SessionLocal = None
Base = declarative_base()

def initialize_database(db_url: str):
    """データベースエンジンとセッションファクトリを初期化します。"""
    global engine, SessionLocal
    if not db_url:
        raise ValueError("データベースURLが設定されていません。データベースを初期化できません。")
    
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    user_name = Column(String)
    patient_id = Column(String, nullable=True)
    user_role = Column(String)
    sender = Column(String) # System, User, Assistant
    message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed = Column(Boolean, default=False, nullable=False, index=True)

def init_db():
    """データベーステーブルを作成します。"""
    if engine is None:
        raise RuntimeError("データベースが初期化されていません。先に initialize_database() を呼び出してください。")
    Base.metadata.create_all(bind=engine)
