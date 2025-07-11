from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import os

Base = declarative_base()

TABLE_SUFFIX = os.getenv("TABLE_SUFFIX", "")

class Session(Base):
    __tablename__ = f"sessions{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    user_name = Column(String, nullable=False)
    user_role = Column(String, nullable=False)
    patient_id = Column(String, nullable=True)
    status = Column(String, default='active', nullable=False, index=True) # e.g., 'active', 'completed'
    thread_id = Column(String, nullable=True) # OpenAI Assistant thread_id
    interview_date = Column(String, nullable=True) # The date of the interview
    patient_version = Column(Integer, nullable=True) # 使用した患者AIプロンプトのバージョン
    interviewer_version = Column(Integer, nullable=True) # 使用した保健師AIプロンプトのバージョン
    evaluator_version = Column(Integer, nullable=True) # 使用した評価AIプロンプトのバージョン
    patient_model = Column(String, nullable=True) # 患者役に使用したモデル名
    interviewer_model = Column(String, nullable=True) # 保健師役に使用したモデル名
    evaluator_model = Column(String, nullable=True) # 評価役に使用したモデル名
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
