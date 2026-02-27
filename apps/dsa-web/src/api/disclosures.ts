import apiClient from './index';

export interface DisclosureItem {
  title: string;
  pub_date: string;
  url?: string | null;
  category?: string | null;
}

export interface DisclosureResponse {
  stock_code: string;
  items: DisclosureItem[];
  total: number;
}

export const disclosuresApi = {
  getDisclosures: async (
    stockCode: string,
    days = 90,
    limit = 20,
  ): Promise<DisclosureResponse> => {
    const resp = await apiClient.get<DisclosureResponse>(
      `/api/v1/disclosures/${stockCode}`,
      { params: { days, limit } },
    );
    return resp.data;
  },
};
