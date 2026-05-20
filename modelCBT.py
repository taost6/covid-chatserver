"""
CBT（Computer-Based Testing）プラットフォーム用データモデル

URL発行モデル：
- 管理者が被験者人数分のアクセストークン付きURLを発行
- 被験者は URL（トークン）経由でアクセス（Cookie非依存）
- 各トークンが1人の被験者に対応

テーブル:
- cbt_access_tokens : 発行されたアクセストークン（被験者単位）
- cbt_progress      : 被験者ごとの課題進捗・能力推定値ログ
"""

import os
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import Session

Base = declarative_base()

TABLE_SUFFIX = os.getenv("TABLE_SUFFIX", "")


class CBTAccessToken(Base):
    """CBT被験者のアクセストークン（URL発行モデル）"""
    __tablename__ = f"cbt_access_tokens{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(200), nullable=True)        # 管理者用メモ（例: "被験者A 山田"）
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=True)


class CBTProgress(Base):
    """CBT被験者ごとの課題進捗・能力推定値ログ"""
    __tablename__ = f"cbt_progress{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    token_id = Column(Integer, nullable=False, index=True)
    patient_id = Column(String(20), nullable=False)
    session_id = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default='in_progress')  # in_progress / completed
    score = Column(Float, nullable=True)               # セッション内得点
    ability_theta = Column(Float, nullable=True)        # このセッション後の能力推定値
    ability_se = Column(Float, nullable=True)           # 標準誤差
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CBTService:
    """CBT トークン・進捗の CRUD 操作"""

    def __init__(self, db: Session):
        self.db = db

    # --- トークン管理 ---

    def create_tokens(self, count: int, labels: Optional[List[str]] = None) -> List[CBTAccessToken]:
        """アクセストークンを一括発行する。labels が指定されればトークンごとにラベルを付与。"""
        created = []
        for i in range(count):
            label = labels[i] if labels and i < len(labels) else None
            tok = CBTAccessToken(
                token=secrets.token_hex(16),  # 32文字の推測困難なトークン
                label=label,
                is_active=True,
            )
            self.db.add(tok)
            created.append(tok)
        self.db.commit()
        for tok in created:
            self.db.refresh(tok)
        return created

    def get_token(self, token_str: str) -> Optional[CBTAccessToken]:
        """トークン文字列から有効なトークンレコードを取得する。"""
        return (
            self.db.query(CBTAccessToken)
            .filter(CBTAccessToken.token == token_str)
            .first()
        )

    def list_tokens(self) -> List[CBTAccessToken]:
        """全トークンを発行日時の降順で取得する。"""
        return (
            self.db.query(CBTAccessToken)
            .order_by(CBTAccessToken.created_at.desc())
            .all()
        )

    def deactivate_token(self, token_id: int) -> bool:
        """トークンを無効化する。"""
        tok = self.db.query(CBTAccessToken).filter(CBTAccessToken.id == token_id).first()
        if not tok:
            return False
        tok.is_active = False
        self.db.commit()
        return True

    def update_label(self, token_id: int, label: Optional[str]) -> Optional[CBTAccessToken]:
        """トークンのラベルを更新する。"""
        tok = self.db.query(CBTAccessToken).filter(CBTAccessToken.id == token_id).first()
        if not tok:
            return None
        tok.label = (label or "").strip() or None
        self.db.commit()
        self.db.refresh(tok)
        return tok

    def touch_token(self, token_id: int) -> None:
        """トークンの最終アクセス日時を更新する。"""
        tok = self.db.query(CBTAccessToken).filter(CBTAccessToken.id == token_id).first()
        if tok:
            tok.last_seen_at = datetime.now(timezone.utc)
            self.db.commit()

    # --- 進捗管理 ---

    def get_progress(self, token_id: int) -> List[CBTProgress]:
        """指定トークンの進捗一覧を取得する。"""
        return (
            self.db.query(CBTProgress)
            .filter(CBTProgress.token_id == token_id)
            .order_by(CBTProgress.started_at.asc())
            .all()
        )

    def get_active_progress(self, token_id: int) -> Optional[CBTProgress]:
        """進行中（in_progress）の課題があれば返す。"""
        return (
            self.db.query(CBTProgress)
            .filter(
                CBTProgress.token_id == token_id,
                CBTProgress.status == 'in_progress',
            )
            .order_by(CBTProgress.started_at.desc())
            .first()
        )

    def start_progress(self, token_id: int, patient_id: str,
                        session_id: Optional[str] = None) -> CBTProgress:
        """新しい課題を開始状態で記録する。"""
        prog = CBTProgress(
            token_id=token_id,
            patient_id=patient_id,
            session_id=session_id,
            status='in_progress',
        )
        self.db.add(prog)
        self.db.commit()
        self.db.refresh(prog)
        return prog

    def finalize_progress(self, progress_id: int, score: Optional[float],
                          ability_theta: Optional[float],
                          ability_se: Optional[float],
                          session_id: Optional[str] = None) -> Optional[CBTProgress]:
        """課題を完了状態にし、得点・能力推定値を記録する。
        session_id が渡された場合は紐付けを更新する。"""
        prog = self.db.query(CBTProgress).filter(CBTProgress.id == progress_id).first()
        if not prog:
            return None
        prog.status = 'completed'
        prog.score = score
        prog.ability_theta = ability_theta
        prog.ability_se = ability_se
        if session_id:
            prog.session_id = session_id
        prog.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(prog)
        return prog
