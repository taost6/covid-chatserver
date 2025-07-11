from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import Session
from typing import Optional, List

Base = declarative_base()

class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    template_type = Column(String(50), nullable=False)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    message_text = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PromptTemplateService:
    def __init__(self, db: Session):
        self.db = db
    
    def get_active_template(self, template_type: str) -> Optional[PromptTemplate]:
        """指定されたtypeのアクティブなテンプレートを取得"""
        return self.db.query(PromptTemplate).filter(
            PromptTemplate.template_type == template_type,
            PromptTemplate.is_active == True
        ).first()
    
    def get_all_templates(self, template_type: str = None) -> List[PromptTemplate]:
        """すべてのテンプレートを取得（オプションでtype絞り込み）"""
        query = self.db.query(PromptTemplate)
        if template_type:
            query = query.filter(PromptTemplate.template_type == template_type)
        return query.order_by(PromptTemplate.created_at.desc()).all()
    
    def create_template(self, template_type: str, prompt_text: str, 
                       message_text: str = None, description: str = None) -> PromptTemplate:
        """新しいテンプレートを作成し、既存のアクティブなテンプレートを非アクティブにする"""
        # 既存のアクティブなテンプレートを非アクティブにする
        existing_active = self.get_active_template(template_type)
        if existing_active:
            existing_active.is_active = False
        
        # 次のバージョン番号を計算
        max_version = self.db.query(func.max(PromptTemplate.version)).filter(
            PromptTemplate.template_type == template_type
        ).scalar()
        next_version = (max_version or 0) + 1
        
        # 新しいテンプレートを作成
        new_template = PromptTemplate(
            template_type=template_type,
            version=next_version,
            prompt_text=prompt_text,
            message_text=message_text,
            description=description,
            is_active=True
        )
        self.db.add(new_template)
        self.db.commit()
        self.db.refresh(new_template)
        return new_template
    
    def update_template(self, template_id: int, prompt_text: str, 
                       message_text: str = None, description: str = None) -> Optional[PromptTemplate]:
        """既存のテンプレートを更新"""
        template = self.db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
        if not template:
            return None
        
        template.prompt_text = prompt_text
        template.message_text = message_text
        template.description = description
        self.db.commit()
        self.db.refresh(template)
        return template
    
    def activate_template(self, template_id: int) -> Optional[PromptTemplate]:
        """指定されたテンプレートをアクティブにし、同じtypeの他のテンプレートを非アクティブにする"""
        template = self.db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
        if not template:
            return None
        
        # 同じtypeの他のテンプレートを非アクティブにする
        self.db.query(PromptTemplate).filter(
            PromptTemplate.template_type == template.template_type,
            PromptTemplate.id != template_id
        ).update({PromptTemplate.is_active: False})
        
        # 指定されたテンプレートをアクティブにする
        template.is_active = True
        self.db.commit()
        self.db.refresh(template)
        return template

def initialize_default_prompts(db: Session):
    """デフォルトのプロンプトを初期化"""
    service = PromptTemplateService(db)
    
    # 既存のプロンプトがあるかチェック
    existing_patient = service.get_active_template('patient')
    existing_interviewer = service.get_active_template('interviewer')
    existing_evaluator = service.get_active_template('evaluator')
    
    # 患者AIプロンプト
    if not existing_patient:
        patient_prompt = """本日は{interview_date_str}です。
以下に示す情報は全て、あなたに関する設定です。
これらの設定を忠実に守り、役になりきって応答してください。
具体的に質問されていることだけに答えてください。
短く簡潔に回答し、最長でも100文字以内で解答してください。
日付について聞かれた際は、年の指定が無ければ年は省略してかまいません。
今日の日付について言及する際は、基本的には「今日」と表現し、日付での回答を求められた場合だけ日付で回答してください。
ユーザー（保健師）が会話を終了しようとしていると判断した場合、例えば『ご協力ありがとうございました』のような感謝の言葉で締めくくった場合は、通常の応答はせず、必ず`end_conversation_and_start_debriefing`ツールを呼び出して会話を終了してください。"""
        
        # 手動でバージョン1を設定（初回のみ）
        patient_template = PromptTemplate(
            template_type='patient',
            version=1,
            prompt_text=patient_prompt,
            message_text='私の名前は{patient_name}です。何でも聞いてください。',
            description='患者AIのデフォルトプロンプト',
            is_active=True
        )
        db.add(patient_template)
        db.commit()
    
    # 保健師AIプロンプト
    if not existing_interviewer:
        interviewer_prompt = """あなたは日本の自治体に所属する保健師です。
ユーザーは感染症に罹患した患者もしくは濃厚接触者です。
これからあなたには、ユーザーに対する聞き取りを行ってもらいます。
これは積極的疫学調査と呼ばれるもので、その中でも「聞き取り」とは、
感染症の発生や拡大を把握・制御するために、患者や関係者から直接情報を収集するプロセスを指します。
具体的には、インタビューを通じて、感染経路、接触者、症状の経過、行動履歴（いつ、どこにいったか、誰と会ったかなど）、リスク要因などを詳細に聞き出すことを意味します。
これらを踏まえた上で、感染経路の特定や、濃厚接触者の把握に役立ちそうな情報を深堀りして、有益な情報を引き出してください。
ユーザーに対する質問は一回につき一つまでとし、回答しやすい質問を心がけてください。"""
        
        # 手動でバージョン1を設定（初回のみ）
        interviewer_template = PromptTemplate(
            template_type='interviewer',
            version=1,
            prompt_text=interviewer_prompt,
            message_text='はじめまして。私は保健師です。これから感染状況に関する質問をさせてください。今の体調はいかがでしょうか？',
            description='保健師AIのデフォルトプロンプト',
            is_active=True
        )
        db.add(interviewer_template)
        db.commit()
    
    # 評価AIプロンプト
    if not existing_evaluator:
        evaluator_prompt = """あなたは保健師の聞き取りスキルを評価する専門家です。
以下の対話履歴を分析し、`submit_debriefing_report`関数を呼び出して詳細な評価レポートを作成してください。

評価の観点：
1. 感染経路の特定に関する情報収集の網羅性
2. 濃厚接触者の把握につながる質問の適切性
3. 時系列（いつ）、場所（どこで）、人物（誰と）の情報収集
4. 質問技法の効果性と患者への配慮
5. 情報の整理と確認の適切性

必ず`submit_debriefing_report`関数を呼び出して評価を提出してください。
良かったポイントは積極的に評価し、改善につながるポジティブなフィードバックをお願いします。"""
        
        # 手動でバージョン1を設定（初回のみ）
        evaluator_template = PromptTemplate(
            template_type='evaluator',
            version=1,
            prompt_text=evaluator_prompt,
            message_text=None,
            description='評価AIのデフォルトプロンプト',
            is_active=True
        )
        db.add(evaluator_template)
        db.commit()