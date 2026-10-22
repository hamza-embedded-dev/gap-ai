import { apiFetch } from './client';

export interface DemoSessionResponse {
  token: string;
  expires_at: string;
  is_demo: boolean;
}

/**
 * Calls the `POST /demo/session` endpoint on the backend to initialize an isolated demo session.
 *
 * @returns {Promise<DemoSessionResponse>} Object containing token, expiration date, and demo flag.
 */
export async function createDemoSession(): Promise<DemoSessionResponse> {
  const data = await apiFetch<DemoSessionResponse>('/demo/session', {
    method: 'POST',
  });

  if (!data || typeof data.token !== 'string' || !data.token.trim()) {
    throw new Error('Invalid demo session response: Token is missing or empty.');
  }

  return data;
}
