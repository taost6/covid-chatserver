export type AssessmentGrade = 'full' | 'incidental' | 'missing' | 'pending';
export interface AssessmentMetrics {
  assessment_version?: string | null;
  evaluator_prompt_version?: number | null;
  evaluator_model?: string | null;
  display_message_count?: number | null;
  initial_message_count?: number | null;
  incidental_item_count?: number | null;
  missing_item_count?: number | null;
  pending_item_count?: number | null;
  confirmation_count?: number | null;
  explanation_count?: number | null;
  other_act_count?: number | null;
  interview_date?: string | null;
}
export interface AssessmentEvidence {
  grade?: AssessmentGrade | null;
  reason?: string | null;
  question_message_ids?: number[] | null;
  answer_message_ids?: number[] | null;
}
export const gradeLabel = (grade?: string | null, collected = false): string => ({
  full: '○ 意図を持った聴取', incidental: '△ 情報の出現のみ',
  missing: '× 未聴取', pending: '保留',
}[grade ?? ''] ?? (collected ? '旧：聴取済み' : '旧：未聴取'));
