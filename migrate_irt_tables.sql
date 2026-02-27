-- IRT評価基盤テーブルのマイグレーション
-- 実行方法: psql -f migrate_irt_tables.sql <database_url>

-- =============================================
-- Table 1: IRT項目タイプカタログ
-- =============================================
CREATE TABLE IF NOT EXISTS irt_item_types (
    id SERIAL PRIMARY KEY,
    catalog_version INTEGER NOT NULL DEFAULT 1,
    code VARCHAR(10) NOT NULL,
    category VARCHAR(5) NOT NULL,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    description TEXT,
    investigation_phase VARCHAR(10),
    pdf_priority VARCHAR(5),
    investigation_direction VARCHAR(10),
    frequency VARCHAR(10),
    intensity VARCHAR(10),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (code, catalog_version)
);

CREATE INDEX IF NOT EXISTS idx_irt_item_types_catalog_version ON irt_item_types (catalog_version);
CREATE INDEX IF NOT EXISTS idx_irt_item_types_category ON irt_item_types (category);
CREATE INDEX IF NOT EXISTS idx_irt_item_types_status ON irt_item_types (status);

-- =============================================
-- Table 2: IRT患者インスタンス（正解表）
-- =============================================
CREATE TABLE IF NOT EXISTS irt_patient_instances (
    id SERIAL PRIMARY KEY,
    catalog_version INTEGER NOT NULL DEFAULT 1,
    patient_id VARCHAR(20) NOT NULL,
    item_type_code VARCHAR(10) NOT NULL,
    instance_number INTEGER NOT NULL,
    date VARCHAR(20),
    description TEXT,
    investigation_direction_override VARCHAR(10),
    scene_category VARCHAR(20),
    density_closed VARCHAR(10),
    density_crowded VARCHAR(10),
    density_close_contact VARCHAR(10),
    related_patient_ids TEXT,
    is_detectable BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (patient_id, item_type_code, instance_number, catalog_version)
);

CREATE INDEX IF NOT EXISTS idx_irt_patient_instances_patient_id ON irt_patient_instances (patient_id);
CREATE INDEX IF NOT EXISTS idx_irt_patient_instances_item_type ON irt_patient_instances (item_type_code);
CREATE INDEX IF NOT EXISTS idx_irt_patient_instances_catalog_version ON irt_patient_instances (catalog_version);
CREATE INDEX IF NOT EXISTS idx_irt_patient_instances_detectable ON irt_patient_instances (is_detectable);

-- =============================================
-- Table 3: IRT応答判定結果（Step 2用）
-- =============================================
CREATE TABLE IF NOT EXISTS irt_response_judgments (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    instance_id INTEGER NOT NULL,
    is_correct BOOLEAN NOT NULL,
    judgment_method VARCHAR(20) NOT NULL DEFAULT 'ai',
    confidence FLOAT,
    evidence_message_ids TEXT,
    notes TEXT,
    judged_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (session_id, instance_id)
);

CREATE INDEX IF NOT EXISTS idx_irt_response_judgments_session ON irt_response_judgments (session_id);
CREATE INDEX IF NOT EXISTS idx_irt_response_judgments_instance ON irt_response_judgments (instance_id);
CREATE INDEX IF NOT EXISTS idx_irt_response_judgments_correct ON irt_response_judgments (is_correct);

-- =============================================
-- TABLE_SUFFIX="_stg" 環境用（必要に応じてコメント解除）
-- =============================================
-- CREATE TABLE IF NOT EXISTS irt_item_types_stg ( ... );
-- CREATE TABLE IF NOT EXISTS irt_patient_instances_stg ( ... );
-- CREATE TABLE IF NOT EXISTS irt_response_judgments_stg ( ... );
