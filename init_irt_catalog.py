"""
IRT項目カタログ v3 初期投入スクリプト

設計ドキュメント: doc/IRT評価項目カタログ設計ドキュメント.md

使用方法:
    DATABASE_URL=postgresql://... python init_irt_catalog.py
"""
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from modelIRT import Base, IRTItemType, IRTItemTypeService
from modelPrompt import Base as PromptBase, PromptTemplate, PromptTemplateService

CATALOG_VERSION = 3

# v3カタログ定義（19項目 + I型候補4項目）
V3_ITEM_TYPES = [
    # D: 疾病臨床情報型（Disease）
    {
        "code": "D-1",
        "category": "D",
        "name_ja": "発症日・初期症状の特定",
        "name_en": "Onset date and initial symptom identification",
        "description": "患者の症状が最初に出た日（発症日）を正確に特定し、初期症状の種類を具体的に確認する。発症日が調査期間の起点を決定するため、調査全体の最も基礎的なステップ。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "◎",
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "D-2",
        "category": "D",
        "name_ja": "症状経過・現在の状態",
        "name_en": "Symptom progression and current status",
        "description": "発症から現在までの症状の推移、重症度、受診歴・検査歴を把握する。患者の状態により聞き取り方法や可能時間が変わるため、調査計画の前提情報。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "◎",
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    # T: 感染追跡可能型（Traceable）
    {
        "code": "T-1",
        "category": "T",
        "name_ja": "同居者間伝播",
        "name_en": "Household transmission",
        "description": "同居する家族・同居人間での感染。日常的・継続的な密接接触による伝播。",
        "investigation_phase": "Phase-A",
        "pdf_priority": "◎",
        "investigation_direction": "both",
        "frequency": "High",
        "intensity": "High",
        "status": "active",
    },
    {
        "code": "T-2",
        "category": "T",
        "name_ja": "既知関係者への訪問伝播",
        "name_en": "Known contact visit transmission",
        "description": "非同居の家族・親族・友人・知人への訪問、または訪問を受けたことによる感染。帰省、見舞い、遊びに行く等の意図的な接触。",
        "investigation_phase": "Phase-A",
        "pdf_priority": "○",
        "investigation_direction": "both",
        "frequency": "Low",
        "intensity": "High",
        "status": "active",
    },
    {
        "code": "T-3",
        "category": "T",
        "name_ja": "組織的集団内伝播",
        "name_en": "Organizational group transmission",
        "description": "組織された場（職場会議、歓迎会、授業、アルバイトのシフト、大学ゼミ・研究室等）での接触による感染。参加者が特定可能な集まりでの伝播。副業・アルバイト、更衣室・休憩室・喫煙場所での接触を含む。",
        "investigation_phase": "Phase-A",
        "pdf_priority": "◎",
        "investigation_direction": "both",
        "frequency": "Variable",
        "intensity": "High",
        "status": "active",
    },
    {
        "code": "T-4",
        "category": "T",
        "name_ja": "ケア関係伝播",
        "name_en": "Healthcare-related transmission",
        "description": "医療・介護における職員⇔患者の接触による感染。職員→患者、患者→職員、職員間（更衣室・休憩室等）を包含。",
        "investigation_phase": "Phase-A",
        "pdf_priority": "◎",
        "investigation_direction": "both",
        "frequency": "High",
        "intensity": "High",
        "status": "active",
    },
    # U: 感染追跡不可能型（Untraceable）
    {
        "code": "U-1",
        "category": "U",
        "name_ja": "日常圏内の不特定多数接触",
        "name_en": "Routine daily contact with unspecified persons",
        "description": "通勤・買い物・外食等、日常的行動の中での曝露機会。外食、買い物、公共交通機関利用をすべて包含。感染可能期間中の行動として一日単位で確認すべき。",
        "investigation_phase": "Phase-A",
        "pdf_priority": "◎",
        "investigation_direction": "both",
        "frequency": "High",
        "intensity": "Variable",
        "status": "active",
    },
    {
        "code": "U-2",
        "category": "U",
        "name_ja": "非日常的外出・移動",
        "name_en": "Non-routine outing and travel",
        "description": "出張、旅行、セミナー参加、イベント鑑賞等、普段のルーティンとは異なる行動。移動距離が長い、初めての場所、多数の不特定者との接触が特徴。",
        "investigation_phase": "Phase-B",
        "pdf_priority": "◎",
        "investigation_direction": "backward",
        "frequency": "Low",
        "intensity": "Variable",
        "status": "active",
    },
    {
        "code": "U-3",
        "category": "U",
        "name_ja": "偶発的同一空間伝播",
        "name_en": "Incidental co-location transmission",
        "description": "意図せず同じ空間に居合わせたことによる感染。面識のない人物間での伝播。飲食店での隣席、待合室等。最も検知困難。",
        "investigation_phase": "Phase-B",
        "pdf_priority": "△",
        "investigation_direction": "backward",
        "frequency": "Low",
        "intensity": "Low",
        "status": "active",
    },
    {
        "code": "U-4",
        "category": "U",
        "name_ja": "症状下での外出・接触",
        "name_en": "Activity while symptomatic",
        "description": "発症後（自覚症状出現後）もなお外出・接触を継続した行動。前向き調査において特に重要。感染拡大の直接的原因となりうる。",
        "investigation_phase": "Phase-A",
        "pdf_priority": "◎",
        "investigation_direction": "forward",
        "frequency": "Variable",
        "intensity": "Variable",
        "status": "active",
    },
    # P: 背景リスク情報型（Personal）
    {
        "code": "P-1",
        "category": "P",
        "name_ja": "ワクチン接種状況・感染履歴",
        "name_en": "Vaccination status and infection history",
        "description": "COVID-19ワクチンの接種歴（接種回数・時期）。過去の感染履歴。重症化リスク評価と感染経路推定に影響。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "◎",
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "P-2",
        "category": "P",
        "name_ja": "基礎疾患・既往歴",
        "name_en": "Pre-existing conditions and medical history",
        "description": "重症化リスクに直結する基礎疾患の有無。糖尿病、高血圧、がん、心臓・血管の病気、喫煙・慢性呼吸器疾患、透析等。治療内容・コントロール状況を含む。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "◎",
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "P-3",
        "category": "P",
        "name_ja": "同居者",
        "name_en": "Cohabitants",
        "description": "同居者の人数・続柄・年齢層。家庭内感染リスクの評価と接触者追跡の基礎情報。高齢者・乳幼児等の脆弱な同居者の有無が重要。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "◎",
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "P-4",
        "category": "P",
        "name_ja": "職業・勤務形態",
        "name_en": "Occupation and work style",
        "description": "職種、勤務場所、勤務形態（在宅/出勤/シフト）、通勤手段。副業・アルバイトの有無と内容を含む。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "◎",
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "P-5",
        "category": "P",
        "name_ja": "感染対策実施状況・感染対策知識",
        "name_en": "Infection prevention practices and knowledge",
        "description": "日常的なマスク着用習慣、手洗い、換気等の感染対策実施状況。喫煙習慣と喫煙場所を含む。症状の有無に関わらない日常的な対策習慣。",
        "investigation_phase": "Phase-C",
        "pdf_priority": "○",
        "investigation_direction": "both",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    # E: 周辺・環境情報型（Environment）
    {
        "code": "E-1",
        "category": "E",
        "name_ja": "接触者の体調情報",
        "name_en": "Health status of contacts",
        "description": "患者が直接接触した人物の体調・発症状況。感染元の手がかりとなる情報。",
        "investigation_phase": "Phase-B",
        "pdf_priority": "◎",
        "investigation_direction": "backward",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "E-2",
        "category": "E",
        "name_ja": "地域・施設の流行状況",
        "name_en": "Regional and facility outbreak status",
        "description": "患者が利用した施設や居住地域での感染流行状況。院内クラスタ、学校での集団感染等。保健師側の事前知識に依存する部分が大きい。",
        "investigation_phase": "Phase-B",
        "pdf_priority": "△",
        "investigation_direction": "backward",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "E-3",
        "category": "E",
        "name_ja": "3密条件の評価",
        "name_en": "Three Cs (Closed, Crowded, Close-contact) assessment",
        "description": "患者が利用した各施設における3密（密閉・密集・密接）条件の体系的評価。増幅因子（大声、歌唱、飲食等）を含む。",
        "investigation_phase": "Phase-B",
        "pdf_priority": "○",
        "investigation_direction": "backward",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    {
        "code": "E-4",
        "category": "E",
        "name_ja": "近所・知人からの噂・情報",
        "name_en": "Information from acquaintances and community",
        "description": "患者が間接的に得た感染関連情報。知人からの連絡、SNS・LINE等での情報共有、家族経由の伝聞等。",
        "investigation_phase": "Phase-B",
        "pdf_priority": "○",
        "investigation_direction": "backward",
        "frequency": None,
        "intensity": None,
        "status": "active",
    },
    # I: 調査プロセス型（Interview）— 候補
    {
        "code": "I-1",
        "category": "I",
        "name_ja": "関係性構築・共感的導入",
        "name_en": "Rapport building and empathetic introduction",
        "description": "適切な自己紹介、調査目的の説明、患者への共感表現ができたか。",
        "investigation_phase": "Phase-C",
        "pdf_priority": None,
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "candidate",
    },
    {
        "code": "I-2",
        "category": "I",
        "name_ja": "記憶喚起支援",
        "name_en": "Memory recall support",
        "description": "患者の記憶を引き出すための工夫ができたか。スケジュール帳・メール・SNS履歴の活用を促したか。",
        "investigation_phase": "Phase-C",
        "pdf_priority": None,
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "candidate",
    },
    {
        "code": "I-3",
        "category": "I",
        "name_ja": "時系列構造化",
        "name_en": "Chronological structuring",
        "description": "発症日を起点に体系的に時系列を構造化して聴取できたか。発症2日前〜現在、次に14日前〜2日前の順序。",
        "investigation_phase": "Phase-C",
        "pdf_priority": None,
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "candidate",
    },
    {
        "code": "I-4",
        "category": "I",
        "name_ja": "情報提供依頼",
        "name_en": "Information provision request",
        "description": "接触者の連絡先や、組織の窓口情報を適切に取得できたか。",
        "investigation_phase": "Phase-C",
        "pdf_priority": None,
        "investigation_direction": "none",
        "frequency": None,
        "intensity": None,
        "status": "candidate",
    },
]




def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL が設定されていません。")
        sys.exit(1)

    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    PromptBase.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        service = IRTItemTypeService(db)

        # 既存のv3カタログがあるかチェック
        existing = service.get_all_item_types(catalog_version=CATALOG_VERSION)
        if existing:
            print(f"カタログ v{CATALOG_VERSION} は既に {len(existing)} 件存在します。スキップします。")
        else:
            # 一括投入
            items_with_version = [
                {**item, "catalog_version": CATALOG_VERSION}
                for item in V3_ITEM_TYPES
            ]
            created = service.bulk_create_item_types(items_with_version)
            active_count = sum(1 for it in created if it.status == 'active')
            candidate_count = sum(1 for it in created if it.status == 'candidate')
            print(f"カタログ v{CATALOG_VERSION}: {len(created)} 件投入完了（active: {active_count}, candidate: {candidate_count}）")

    finally:
        db.close()


if __name__ == "__main__":
    main()
