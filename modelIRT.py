from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import Session
from typing import Optional, List
import os
import json

Base = declarative_base()

TABLE_SUFFIX = os.getenv("TABLE_SUFFIX", "")


class IRTItemType(Base):
    """IRT項目タイプカタログ（v3: 19項目型）"""
    __tablename__ = f"irt_item_types{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    catalog_version = Column(Integer, nullable=False, default=1)
    code = Column(String(10), nullable=False)           # e.g., "T-3"
    category = Column(String(5), nullable=False)        # D, T, U, P, E, I
    name_ja = Column(Text, nullable=False)
    name_en = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    investigation_phase = Column(String(10), nullable=True)    # Phase-A, Phase-B, Phase-C
    pdf_priority = Column(String(5), nullable=True)            # ◎, ○, △
    investigation_direction = Column(String(10), nullable=True)  # forward, backward, both, none
    frequency = Column(String(10), nullable=True)              # High, Low, Variable
    intensity = Column(String(10), nullable=True)              # High, Low, Variable
    status = Column(String(20), nullable=False, default='active')  # active, candidate, deprecated
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IRTPatientInstance(Base):
    """患者ごとのIRT項目インスタンス（正解表）"""
    __tablename__ = f"irt_patient_instances{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    catalog_version = Column(Integer, nullable=False, default=1)
    patient_id = Column(String(20), nullable=False, index=True)
    item_type_code = Column(String(10), nullable=False, index=True)
    instance_number = Column(Integer, nullable=False)
    date = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    investigation_direction_override = Column(String(10), nullable=True)
    scene_category = Column(String(20), nullable=True)
    density_closed = Column(String(10), nullable=True)       # 密閉: High, Low, Unknown
    density_crowded = Column(String(10), nullable=True)      # 密集: High, Low, Unknown
    density_close_contact = Column(String(10), nullable=True)  # 密接: High, Low, Unknown
    related_patient_ids = Column(Text, nullable=True)        # JSON array string
    is_detectable = Column(Boolean, default=True, nullable=False)
    is_excluded_from_analysis = Column(Boolean, default=False)
    risk_score = Column(Float, nullable=True)
    pairwise_risk_score = Column(Float, nullable=True)
    pairwise_risk_score_forward = Column(Float, nullable=True)
    pairwise_risk_score_backward = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IRTResponseJudgment(Base):
    """セッションごとの正誤判定結果（Step 2用）"""
    __tablename__ = f"irt_response_judgments{TABLE_SUFFIX}"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    instance_id = Column(Integer, nullable=False, index=True)
    is_correct = Column(Boolean, nullable=False)
    judgment_method = Column(String(20), nullable=False, default='ai')  # ai, manual, hybrid
    confidence = Column(Float, nullable=True)
    evidence_message_ids = Column(Text, nullable=True)  # JSON array of chat_log IDs
    notes = Column(Text, nullable=True)
    judged_at = Column(DateTime(timezone=True), server_default=func.now())
    # 来歴（プロヴェナンス）: 判定条件をデータから検証可能にする
    evaluator_model = Column(String(50), nullable=True)          # 判定に使用したLLMモデル名
    evaluator_prompt_version = Column(Integer, nullable=True)    # 判定に使用した評価者プロンプトのバージョン
    votes_total = Column(Integer, nullable=True)                 # 多数決の投票数（単発判定は1）
    votes_correct = Column(Integer, nullable=True)               # 「正答」と判定した票数


class IRTItemTypeService:
    """IRT項目タイプカタログのCRUD操作"""
    def __init__(self, db: Session):
        self.db = db

    def get_all_item_types(self, catalog_version: int = None,
                           category: str = None,
                           status: str = None) -> List[IRTItemType]:
        query = self.db.query(IRTItemType)
        if catalog_version is not None:
            query = query.filter(IRTItemType.catalog_version == catalog_version)
        if category:
            query = query.filter(IRTItemType.category == category)
        if status:
            query = query.filter(IRTItemType.status == status)
        return query.order_by(IRTItemType.code).all()

    def get_item_type_by_code(self, code: str,
                              catalog_version: int = None) -> Optional[IRTItemType]:
        query = self.db.query(IRTItemType).filter(IRTItemType.code == code)
        if catalog_version is not None:
            query = query.filter(IRTItemType.catalog_version == catalog_version)
        return query.first()

    def get_latest_catalog_version(self) -> int:
        result = self.db.query(func.max(IRTItemType.catalog_version)).scalar()
        return result or 0

    def create_item_type(self, catalog_version: int, code: str, category: str,
                         name_ja: str, name_en: str, description: str = None,
                         investigation_phase: str = None, pdf_priority: str = None,
                         investigation_direction: str = None, frequency: str = None,
                         intensity: str = None, status: str = 'active') -> IRTItemType:
        item_type = IRTItemType(
            catalog_version=catalog_version, code=code, category=category,
            name_ja=name_ja, name_en=name_en, description=description,
            investigation_phase=investigation_phase, pdf_priority=pdf_priority,
            investigation_direction=investigation_direction,
            frequency=frequency, intensity=intensity, status=status
        )
        self.db.add(item_type)
        self.db.commit()
        self.db.refresh(item_type)
        return item_type

    def update_item_type(self, item_id: int, **kwargs) -> Optional[IRTItemType]:
        item = self.db.query(IRTItemType).filter(IRTItemType.id == item_id).first()
        if not item:
            return None
        for key, value in kwargs.items():
            if hasattr(item, key) and key not in ('id', 'created_at'):
                setattr(item, key, value)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_item_type(self, item_id: int) -> bool:
        item = self.db.query(IRTItemType).filter(IRTItemType.id == item_id).first()
        if not item:
            return False
        self.db.delete(item)
        self.db.commit()
        return True

    def bulk_create_item_types(self, items: List[dict]) -> List[IRTItemType]:
        item_types = [IRTItemType(**item) for item in items]
        self.db.add_all(item_types)
        self.db.commit()
        for it in item_types:
            self.db.refresh(it)
        return item_types


class IRTPatientInstanceService:
    """IRT患者インスタンスのCRUD操作"""
    def __init__(self, db: Session):
        self.db = db

    def get_instances_for_patient(self, patient_id: str,
                                  catalog_version: int = None) -> List[IRTPatientInstance]:
        query = self.db.query(IRTPatientInstance).filter(
            IRTPatientInstance.patient_id == patient_id
        )
        if catalog_version is not None:
            query = query.filter(IRTPatientInstance.catalog_version == catalog_version)
        return query.order_by(IRTPatientInstance.item_type_code,
                              IRTPatientInstance.instance_number).all()

    def get_instances_by_item_type(self, item_type_code: str,
                                    catalog_version: int = None) -> List[IRTPatientInstance]:
        query = self.db.query(IRTPatientInstance).filter(
            IRTPatientInstance.item_type_code == item_type_code
        )
        if catalog_version is not None:
            query = query.filter(IRTPatientInstance.catalog_version == catalog_version)
        return query.order_by(IRTPatientInstance.patient_id,
                              IRTPatientInstance.instance_number).all()

    def create_instance(self, catalog_version: int, patient_id: str,
                        item_type_code: str, instance_number: int,
                        date: str = None, description: str = None,
                        investigation_direction_override: str = None,
                        scene_category: str = None,
                        density_closed: str = None,
                        density_crowded: str = None,
                        density_close_contact: str = None,
                        related_patient_ids: list = None,
                        is_detectable: bool = True,
                        notes: str = None) -> IRTPatientInstance:
        instance = IRTPatientInstance(
            catalog_version=catalog_version, patient_id=patient_id,
            item_type_code=item_type_code, instance_number=instance_number,
            date=date, description=description,
            investigation_direction_override=investigation_direction_override,
            scene_category=scene_category,
            density_closed=density_closed, density_crowded=density_crowded,
            density_close_contact=density_close_contact,
            related_patient_ids=json.dumps(related_patient_ids) if related_patient_ids else None,
            is_detectable=is_detectable, notes=notes
        )
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def update_instance(self, instance_id: int, **kwargs) -> Optional[IRTPatientInstance]:
        inst = self.db.query(IRTPatientInstance).filter(IRTPatientInstance.id == instance_id).first()
        if not inst:
            return None
        for key, value in kwargs.items():
            if hasattr(inst, key) and key not in ('id', 'created_at'):
                if key == 'related_patient_ids' and isinstance(value, list):
                    value = json.dumps(value)
                setattr(inst, key, value)
        self.db.commit()
        self.db.refresh(inst)
        return inst

    def delete_instance(self, instance_id: int) -> bool:
        inst = self.db.query(IRTPatientInstance).filter(IRTPatientInstance.id == instance_id).first()
        if not inst:
            return False
        self.db.delete(inst)
        self.db.commit()
        return True

    def bulk_create_instances(self, instances: List[dict]) -> List[IRTPatientInstance]:
        for inst in instances:
            if 'related_patient_ids' in inst and isinstance(inst['related_patient_ids'], list):
                inst['related_patient_ids'] = json.dumps(inst['related_patient_ids'])
        patient_instances = [IRTPatientInstance(**inst) for inst in instances]
        self.db.add_all(patient_instances)
        self.db.commit()
        for pi in patient_instances:
            self.db.refresh(pi)
        return patient_instances

    def get_scenario_matrix(self, catalog_version: int = None) -> dict:
        """シナリオ×項目マトリクスを生成
        Returns: {patient_id: {item_type_code: [instance_numbers]}}
        """
        query = self.db.query(IRTPatientInstance)
        if catalog_version is not None:
            query = query.filter(IRTPatientInstance.catalog_version == catalog_version)
        instances = query.all()

        matrix = {}
        for inst in instances:
            if inst.patient_id not in matrix:
                matrix[inst.patient_id] = {}
            if inst.item_type_code not in matrix[inst.patient_id]:
                matrix[inst.patient_id][inst.item_type_code] = []
            matrix[inst.patient_id][inst.item_type_code].append(inst.instance_number)
        return matrix


class IRTResponseJudgmentService:
    """IRT正誤判定結果のCRUD操作"""
    def __init__(self, db: Session):
        self.db = db

    def create_judgment(self, session_id: str, instance_id: int,
                        is_correct: bool, judgment_method: str = 'ai',
                        confidence: float = None,
                        evidence_message_ids: list = None,
                        notes: str = None) -> IRTResponseJudgment:
        judgment = IRTResponseJudgment(
            session_id=session_id, instance_id=instance_id,
            is_correct=is_correct, judgment_method=judgment_method,
            confidence=confidence,
            evidence_message_ids=json.dumps(evidence_message_ids) if evidence_message_ids else None,
            notes=notes
        )
        self.db.add(judgment)
        self.db.commit()
        self.db.refresh(judgment)
        return judgment

    def bulk_create_judgments(self, judgments: List[dict]) -> List[IRTResponseJudgment]:
        objs = []
        for j in judgments:
            if 'evidence_message_ids' in j and isinstance(j['evidence_message_ids'], list):
                j['evidence_message_ids'] = json.dumps(j['evidence_message_ids'])
            objs.append(IRTResponseJudgment(**j))
        self.db.add_all(objs)
        self.db.commit()
        for o in objs:
            self.db.refresh(o)
        return objs

    def get_judgments_for_session(self, session_id: str) -> List[IRTResponseJudgment]:
        return self.db.query(IRTResponseJudgment).filter(
            IRTResponseJudgment.session_id == session_id
        ).order_by(IRTResponseJudgment.instance_id).all()

    def get_judgments_for_instance(self, instance_id: int) -> List[IRTResponseJudgment]:
        return self.db.query(IRTResponseJudgment).filter(
            IRTResponseJudgment.instance_id == instance_id
        ).order_by(IRTResponseJudgment.session_id).all()

    def get_judgments_by_instance_ids(self, instance_ids: List[int]) -> List[IRTResponseJudgment]:
        """複数インスタンスIDの全判定結果を一括取得"""
        if not instance_ids:
            return []
        return self.db.query(IRTResponseJudgment).filter(
            IRTResponseJudgment.instance_id.in_(instance_ids)
        ).order_by(IRTResponseJudgment.instance_id, IRTResponseJudgment.session_id).all()

    def delete_judgments_for_session(self, session_id: str) -> int:
        count = self.db.query(IRTResponseJudgment).filter(
            IRTResponseJudgment.session_id == session_id
        ).delete()
        self.db.commit()
        return count

    def delete_judgments_for_instance_ids(self, instance_ids: List[int]) -> int:
        """指定インスタンスIDに紐づく全判定結果を削除"""
        if not instance_ids:
            return 0
        count = self.db.query(IRTResponseJudgment).filter(
            IRTResponseJudgment.instance_id.in_(instance_ids)
        ).delete(synchronize_session='fetch')
        self.db.commit()
        return count
