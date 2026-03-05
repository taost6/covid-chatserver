export interface IRTItemType {
  id: number;
  catalog_version: number;
  code: string;
  category: string;
  name_ja: string;
  name_en: string;
  description: string | null;
  investigation_phase: string | null;
  pdf_priority: string | null;
  investigation_direction: string | null;
  frequency: string | null;
  intensity: string | null;
  status: string;
  created_at: string;
}

export interface IRTPatientInstance {
  id: number;
  catalog_version: number;
  patient_id: string;
  item_type_code: string;
  instance_number: number;
  date: string | null;
  description: string | null;
  investigation_direction_override: string | null;
  scene_category: string | null;
  density_closed: string | null;
  density_crowded: string | null;
  density_close_contact: string | null;
  related_patient_ids: string | null;
  is_detectable: boolean;
  notes: string | null;
  created_at: string;
}

export interface IRTResponseJudgment {
  id: number;
  session_id: string;
  instance_id: number;
  is_correct: boolean;
  judgment_method: string;
  confidence: number | null;
  evidence_message_ids: string | null;
  notes: string | null;
  judged_at: string;
}

export interface IRTJudgmentEvaluateResult {
  session_id: string;
  judged_count: number;
  judgments: IRTResponseJudgment[];
}

export interface BatchStartResponse {
  batch_id: string;
  total_tasks: number;
}

export interface BatchResultEntry {
  session_id: string;
  patient_id: string;
  run_number: number;
  status: string;
  correct_count: number | null;
  total_count: number | null;
  error: string | null;
}

export interface BatchStatus {
  batch_id: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  running: number;
  results: BatchResultEntry[];
}

export interface PatientItemJudgmentDetail {
  session_id: string;
  is_correct: boolean;
  confidence: number | null;
  notes: string | null;
}

export interface PatientItemStat {
  instance_id: number;
  item_type_code: string;
  instance_number: number;
  description: string | null;
  is_detectable: boolean;
  total_judgments: number;
  correct_count: number;
  accuracy: number;
  sessions: PatientItemJudgmentDetail[];
}

export interface PatientSessionStat {
  session_id: string;
  created_at: string | null;
  nurse_model: string | null;
  patient_model: string | null;
  correct_count: number;
  total_count: number;
  accuracy: number;
}

export interface PatientCategoryStat {
  category: string;
  total_instances: number;
  avg_accuracy: number;
}

export interface PatientStatsResponse {
  patient_id: string;
  total_sessions: number;
  sessions: PatientSessionStat[];
  item_stats: PatientItemStat[];
  category_stats: PatientCategoryStat[];
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const defaultHeaders = { 'Content-Type': 'application/json' };
  const config: RequestInit = {
    headers: { ...defaultHeaders, ...options.headers },
    ...options,
  };

  try {
    const response = await fetch(url, config);
    if (!response.ok) {
      const errorText = await response.text();
      throw new ApiError(response.status, `HTTP error! status: ${response.status}, text: ${errorText}`);
    }
    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

function baseUrl(): string {
  const protocol = window.location.protocol.replace(':', '');
  const host = window.location.host;
  return `${protocol}://${host}`;
}

export const irtApi = {
  // 項目タイプ
  async getItemTypes(params?: {
    catalog_version?: number;
    category?: string;
    status?: string;
  }): Promise<IRTItemType[]> {
    const query = new URLSearchParams();
    if (params?.catalog_version) query.set('catalog_version', String(params.catalog_version));
    if (params?.category) query.set('category', params.category);
    if (params?.status) query.set('status', params.status);
    const qs = query.toString();
    return await request<IRTItemType[]>(`${baseUrl()}/v1/irt/item-types${qs ? '?' + qs : ''}`);
  },

  async getItemType(code: string): Promise<IRTItemType> {
    return await request<IRTItemType>(`${baseUrl()}/v1/irt/item-types/${code}`);
  },

  async bulkCreateItemTypes(items: Record<string, unknown>[]): Promise<{ created: number }> {
    return await request<{ created: number }>(`${baseUrl()}/v1/irt/item-types/bulk`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    });
  },

  async updateItemType(itemId: number, data: Record<string, unknown>): Promise<IRTItemType> {
    return await request<IRTItemType>(`${baseUrl()}/v1/irt/item-types/${itemId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async deleteItemType(itemId: number): Promise<{ deleted: boolean }> {
    return await request<{ deleted: boolean }>(`${baseUrl()}/v1/irt/item-types/${itemId}`, {
      method: 'DELETE',
    });
  },

  // 患者インスタンス
  async getPatientInstances(patientId: string, catalogVersion?: number): Promise<IRTPatientInstance[]> {
    const query = catalogVersion ? `?catalog_version=${catalogVersion}` : '';
    return await request<IRTPatientInstance[]>(`${baseUrl()}/v1/irt/patient-instances/${patientId}${query}`);
  },

  async bulkCreatePatientInstances(instances: Record<string, unknown>[]): Promise<{ created: number }> {
    return await request<{ created: number }>(`${baseUrl()}/v1/irt/patient-instances/bulk`, {
      method: 'POST',
      body: JSON.stringify({ instances }),
    });
  },

  async updatePatientInstance(instanceId: number, data: Record<string, unknown>): Promise<IRTPatientInstance> {
    return await request<IRTPatientInstance>(`${baseUrl()}/v1/irt/patient-instances/${instanceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  async deletePatientInstance(instanceId: number): Promise<{ deleted: boolean }> {
    return await request<{ deleted: boolean }>(`${baseUrl()}/v1/irt/patient-instances/${instanceId}`, {
      method: 'DELETE',
    });
  },

  // シナリオマトリクス
  async getScenarioMatrix(catalogVersion?: number): Promise<Record<string, Record<string, number[]>>> {
    const query = catalogVersion ? `?catalog_version=${catalogVersion}` : '';
    return await request<Record<string, Record<string, number[]>>>(`${baseUrl()}/v1/irt/scenario-matrix${query}`);
  },

  // 正誤判定
  async evaluateSession(sessionId: string): Promise<IRTJudgmentEvaluateResult> {
    return await request<IRTJudgmentEvaluateResult>(`${baseUrl()}/v1/irt/judgments/evaluate/${sessionId}`, {
      method: 'POST',
    });
  },

  async getSessionJudgments(sessionId: string): Promise<IRTResponseJudgment[]> {
    return await request<IRTResponseJudgment[]>(`${baseUrl()}/v1/irt/judgments/session/${sessionId}`);
  },

  async getInstanceJudgments(instanceId: number): Promise<IRTResponseJudgment[]> {
    return await request<IRTResponseJudgment[]>(`${baseUrl()}/v1/irt/judgments/instance/${instanceId}`);
  },

  async getPatientStats(patientId: string): Promise<PatientStatsResponse> {
    return await request<PatientStatsResponse>(`${baseUrl()}/v1/irt/judgments/patient/${patientId}`);
  },

  // プロンプトバージョン一覧
  async getPrompts(templateType?: string): Promise<Array<{
    id: number;
    template_type: string;
    version: number;
    description: string | null;
    is_active: boolean;
  }>> {
    const query = templateType ? `?template_type=${templateType}` : '';
    return await request(`${baseUrl()}/v1/prompts${query}`);
  },

  // セッション一覧（判定対象選択用）
  async getSessions(): Promise<Array<{
    session_id: string;
    user_name: string;
    user_role: string;
    patient_id: string | null;
    started_at: string;
  }>> {
    return await request(`${baseUrl()}/v1/logs`);
  },

  // バッチ実行
  async startBatch(
    patientIds: string[],
    runsPerPatient: number,
    concurrency: number,
    nurseModel: string = 'gpt-4.1',
    patientModel: string = 'gpt-4.1',
    evaluatorModel: string = 'gpt-4.1',
    patientPromptVersion: number | null = null,
    interviewerPromptVersion: number | null = null,
    evaluatorPromptVersion: number | null = null,
  ): Promise<BatchStartResponse> {
    const body: Record<string, unknown> = {
      patient_ids: patientIds,
      runs_per_patient: runsPerPatient,
      concurrency,
      nurse_model: nurseModel,
      patient_model: patientModel,
      evaluator_model: evaluatorModel,
    };
    if (patientPromptVersion !== null) body.patient_prompt_version = patientPromptVersion;
    if (interviewerPromptVersion !== null) body.interviewer_prompt_version = interviewerPromptVersion;
    if (evaluatorPromptVersion !== null) body.evaluator_prompt_version = evaluatorPromptVersion;
    return await request<BatchStartResponse>(`${baseUrl()}/v1/irt/batch/start`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  async getBatchStatus(batchId: string): Promise<BatchStatus> {
    return await request<BatchStatus>(`${baseUrl()}/v1/irt/batch/status/${batchId}`);
  },

  async stopBatch(batchId: string): Promise<{ stopped: boolean }> {
    return await request<{ stopped: boolean }>(`${baseUrl()}/v1/irt/batch/stop/${batchId}`, {
      method: 'POST',
    });
  },
};
