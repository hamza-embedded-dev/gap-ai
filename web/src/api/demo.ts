import { apiFetch } from './client';

export interface DemoSessionResponse {
  token: string;
  expires_at: string;
  is_demo: boolean;
}

/**
 * Backend'deki `POST /demo/session` uç noktasını çağırarak izole bir demo oturumu başlatır.
 *
 * @returns {Promise<DemoSessionResponse>} Token, son kullanma tarihi ve demo bayrağı içeren nesne.
 */
export async function createDemoSession(): Promise<DemoSessionResponse> {
  const data = await apiFetch<DemoSessionResponse>('/demo/session', {
    method: 'POST',
  });

  if (!data || typeof data.token !== 'string' || !data.token.trim()) {
    throw new Error('Geçersiz demo oturum yanıtı: Token verisi eksik veya boş.');
  }

  return data;
}
