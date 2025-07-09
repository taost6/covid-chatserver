import type { 
  ApiResponse, 
  PatientListResponse, 
  PatientInfo, 
  SessionRestoreResponse,
  UserRole
} from '@/types';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(
  url: string, 
  options: RequestInit = {}
): Promise<T> {
  const defaultHeaders = {
    'Content-Type': 'application/json',
  };

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
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(0, `Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export const api = {
  // 患者関連API
  async getPatientIds(): Promise<string[]> {
    const protocol = window.location.protocol.replace(':', '');
    const host = window.location.host;
    const url = `${protocol}://${host}/v1/patients`;
    
    const response = await request<PatientListResponse>(url);
    return response.patient_ids?.map(String) || [];
  },

  async getPatientDetails(patientId: string): Promise<PatientInfo> {
    const protocol = window.location.protocol.replace(':', '');
    const host = window.location.host;
    const url = `${protocol}://${host}/v1/patient/${patientId}`;
    
    return await request<PatientInfo>(url);
  },

  // セッション関連API
  async restoreSession(sessionId: string): Promise<SessionRestoreResponse> {
    const protocol = window.location.protocol.replace(':', '');
    const host = window.location.host;
    const url = `${protocol}://${host}/v1/session/${sessionId}`;
    
    return await request<SessionRestoreResponse>(url);
  },

  async registerUser(userData: {
    user_name: string;
    user_role: UserRole;
    target_patient_id?: string;
  }): Promise<{ user_id: string; session_id: string; msg_type: string }> {
    const protocol = window.location.protocol.replace(':', '');
    const host = window.location.host;
    const url = `${protocol}://${host}/v1`;
    
    const body = {
      msg_type: 'RegistrationRequest',
      ...userData,
    };

    return await request(url, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
};

export { ApiError };