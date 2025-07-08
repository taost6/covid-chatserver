// チャット関連の型定義
export interface MessageInfo {
  role: '保健師' | '患者' | '評価者' | 'system';
  text: string;
}

export interface ChatMessage {
  sender: 'user' | 'assistant' | 'system';
  message: string;
  icon: string;
}

// ユーザー関連の型定義
export type UserRole = '保健師' | '患者' | '評価者';
export type UserStatus = 'Initial' | 'Registered' | 'Prepared' | 'Established' | 'Waiting';

export interface User {
  userId: string;
  userName: string;
  role: UserRole;
  status: UserStatus;
  targetPatientId?: string;
  sessionId?: string;
}

// 患者情報の型定義
export interface PatientInfo {
  id: string;
  name: string;
  age: number;
  gender: string;
  birthDate: string;
  residence: string;
  infectionDate?: string;
  onsetDate?: string;
  profile?: string;
  notes?: string;
}

// セッション関連の型定義
export interface SessionInfo {
  sessionId: string;
  userId: string;
}

// 評価関連の型定義
export interface MicroEvaluation {
  utterance: string;
  evaluation_symbol: '◎' | '○' | '△' | '✕';
  advice: string;
}

export interface DebriefingData {
  overall_score: number;
  information_retrieval_ratio: string;
  information_quality: string;
  micro_evaluations: MicroEvaluation[];
  overall_comment: string;
  error?: string;
}

// WebSocket メッセージの型定義
export interface WebSocketMessage {
  msg_type: string;
  session_id?: string;
  user_id?: string;
  user_msg?: string;
  user_status?: string;
  interview_date?: string;
  reason?: string;
  debriefing_data?: DebriefingData;
}

// API レスポンスの型定義
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface PatientListResponse {
  patient_ids: string[];
}

export interface SessionRestoreResponse {
  session_id: string;
  user_id: string;
  user_name: string;
  user_role: UserRole;
  patient_id?: string;
  chat_history: ChatMessage[];
  patient_info: PatientInfo;
  interview_date: string;
}