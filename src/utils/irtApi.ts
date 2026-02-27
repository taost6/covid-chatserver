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

  // シナリオマトリクス
  async getScenarioMatrix(catalogVersion?: number): Promise<Record<string, Record<string, number[]>>> {
    const query = catalogVersion ? `?catalog_version=${catalogVersion}` : '';
    return await request<Record<string, Record<string, number[]>>>(`${baseUrl()}/v1/irt/scenario-matrix${query}`);
  },
};
