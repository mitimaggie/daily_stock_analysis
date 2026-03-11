import apiClient from './index';

export interface ConfigFieldSchema {
  label: string;
  type: 'text' | 'password' | 'number' | 'select' | 'boolean';
  placeholder?: string;
  description?: string;
  default?: string;
  options?: string[];
}

export interface ConfigSchemaResponse {
  success: boolean;
  schema: Record<string, Record<string, ConfigFieldSchema>>;
}

export interface ConfigValuesResponse {
  success: boolean;
  values: Record<string, string>;
}

export interface ConfigUpdateResponse {
  success: boolean;
  updated_keys?: string[];
  error?: string;
}

export const configApi = {
  getSchema: async () => {
    const res = await apiClient.get<ConfigSchemaResponse>('/api/v1/config/schema');
    return res.data;
  },
  getValues: async () => {
    const res = await apiClient.get<ConfigValuesResponse>('/api/v1/config/values');
    return res.data;
  },
  update: async (updates: Record<string, string>) => {
    const res = await apiClient.post<ConfigUpdateResponse>('/api/v1/config/update', updates);
    return res.data;
  }
};
