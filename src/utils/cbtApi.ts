// CBT（Computer-Based Testing）プラットフォーム API クライアント

export interface CBTTask {
  progress_id: number;
  patient_id: string;
  session_id: string | null;
  status: string;
  score: number | null;
  ability_theta: number | null;
  ability_se: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface CBTTokenInfo {
  token: string;
  label: string | null;
  is_active: boolean;
  completed_count: number;
  active_task: CBTTask | null;
  progress: CBTTask[];
}

export interface CBTNextTask {
  next_patient_id: string | null;
  all_completed: boolean;
  completed_count: number;
  total_count: number;
}

export interface CBTResultItem {
  instance_id: number;
  item_type_code: string;
  description: string | null;
  risk_score: number | null;
  collected: boolean;
}

export interface CBTResult {
  progress_id: number;
  patient_id: string;
  score: number;
  total_item_count: number;
  collected_item_count: number;
  items: CBTResultItem[];
}

export interface CBTAdminToken {
  id: number;
  token: string;
  label: string | null;
  is_active: boolean;
  created_at: string | null;
  last_seen_at: string | null;
  completed_count: number;
  total_count: number;
}

export interface CBTAdminTokenDetail extends CBTAdminToken {
  average_score: number | null;
  progress: CBTTask[];
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
    ...options,
    headers: { ...defaultHeaders, ...options.headers },
  };
  try {
    const response = await fetch(url, config);
    if (!response.ok) {
      const errorText = await response.text();
      throw new ApiError(response.status, `HTTP ${response.status}: ${errorText}`);
    }
    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown'}`);
  }
}

function baseUrl(): string {
  const protocol = window.location.protocol.replace(':', '');
  const host = window.location.host;
  return `${protocol}://${host}`;
}

function adminHeaders(adminKey: string): Record<string, string> {
  return adminKey ? { 'X-Admin-Key': adminKey } : {};
}

export const cbtApi = {
  // --- 被験者向け ---

  async getTokenInfo(token: string): Promise<CBTTokenInfo> {
    return request<CBTTokenInfo>(`${baseUrl()}/v1/cbt/t/${token}`);
  },

  async getNextTask(token: string): Promise<CBTNextTask> {
    return request<CBTNextTask>(`${baseUrl()}/v1/cbt/t/${token}/next-task`);
  },

  async startTask(token: string, patientId: string, sessionId?: string): Promise<CBTTask> {
    return request<CBTTask>(`${baseUrl()}/v1/cbt/t/${token}/tasks/start`, {
      method: 'POST',
      body: JSON.stringify({ patient_id: patientId, session_id: sessionId ?? null }),
    });
  },

  async finalizeTask(
    token: string,
    progressId: number,
    payload: { session_id?: string; score?: number; ability_theta?: number; ability_se?: number },
  ): Promise<CBTTask> {
    return request<CBTTask>(`${baseUrl()}/v1/cbt/t/${token}/tasks/${progressId}/finalize`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async scoreTask(token: string, progressId: number, sessionId?: string): Promise<CBTResult> {
    return request<CBTResult>(`${baseUrl()}/v1/cbt/t/${token}/tasks/${progressId}/score`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId ?? null }),
    });
  },

  // --- 管理者向け ---

  async issueTokens(adminKey: string, count: number, labels?: string[]): Promise<CBTAdminToken[]> {
    return request<CBTAdminToken[]>(`${baseUrl()}/v1/cbt/admin/tokens`, {
      method: 'POST',
      headers: adminHeaders(adminKey),
      body: JSON.stringify({ count, labels: labels ?? null }),
    });
  },

  async listTokens(adminKey: string): Promise<CBTAdminToken[]> {
    return request<CBTAdminToken[]>(`${baseUrl()}/v1/cbt/admin/tokens`, {
      headers: adminHeaders(adminKey),
    });
  },

  async deactivateToken(adminKey: string, tokenId: number): Promise<{ deactivated: boolean }> {
    return request<{ deactivated: boolean }>(
      `${baseUrl()}/v1/cbt/admin/tokens/${tokenId}/deactivate`,
      { method: 'POST', headers: adminHeaders(adminKey) },
    );
  },

  async updateTokenLabel(adminKey: string, tokenId: number, label: string): Promise<CBTAdminToken> {
    return request<CBTAdminToken>(`${baseUrl()}/v1/cbt/admin/tokens/${tokenId}`, {
      method: 'PATCH',
      headers: adminHeaders(adminKey),
      body: JSON.stringify({ label }),
    });
  },

  async getTokenDetail(adminKey: string, tokenId: number): Promise<CBTAdminTokenDetail> {
    return request<CBTAdminTokenDetail>(
      `${baseUrl()}/v1/cbt/admin/tokens/${tokenId}/detail`,
      { headers: adminHeaders(adminKey) },
    );
  },

  exportCsvUrl(): string {
    return `${baseUrl()}/v1/cbt/admin/tokens/export.csv`;
  },
};
