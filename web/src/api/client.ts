import { getStoredToken } from '../utils/auth.ts';

/**
 * Ortam değişkeninden API temel URL'i; varsayılan olarak Vite dev proxy'si için '/api' kullanılır.
 */
const API_BASE = (
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) ||
  '/api'
).replace(/\/+$/, '');

export interface ApiErrorPayload {
  error?: string;
  message?: string;
  detail?: string;
}

export class ApiError extends Error {
  public status: number;
  public errorType: string;

  constructor(message: string, status: number, errorType: string = 'api_error') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorType = errorType;
  }
}

/**
 * GAP-AI backend API istemcisi.
 * - Kayıtlı token varsa otomatik `Authorization: Bearer <token>` başlığı ekler.
 * - JSON gövdeleri için `Content-Type: application/json` başlığını ekler.
 * - HTTP hatalarını `ApiError` nesnesi olarak fırlatır.
 */
export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = `${API_BASE}${normalizedEndpoint}`;

  const headers = new Headers(options.headers || {});

  // Kayıtlı Bearer token varsa başlığa ekle:
  const token = getStoredToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  // İstek gövdesi varsa ve FormData değilse Content-Type JSON yap:
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err) {
    const originalMessage = err instanceof Error ? err.message : 'Ağ hatası';
    throw new ApiError(
      `Sunucuya bağlanılamadı (${originalMessage}). Backend servisinin çalıştığından emin olun.`,
      0,
      'network_error'
    );
  }

  // HTTP hata kodlarını ayrıştır:
  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText || 'Bilinmeyen hata'}`;
    let errorType = 'http_error';

    try {
      const errorJson = (await response.json()) as ApiErrorPayload;
      if (errorJson.message) {
        errorMessage = errorJson.message;
      } else if (errorJson.detail) {
        errorMessage = errorJson.detail;
      }
      if (errorJson.error) {
        errorType = errorJson.error;
      }
    } catch {
      // Yanıt gövdesi JSON değilse varsayılan HTTP durum metni kullanılır.
    }

    throw new ApiError(errorMessage, response.status, errorType);
  }

  // 204 No Content veya boş yanıtlar:
  if (response.status === 204) {
    return {} as T;
  }

  const rawText = await response.text();
  if (!rawText || !rawText.trim()) {
    return {} as T;
  }

  try {
    return JSON.parse(rawText) as T;
  } catch {
    throw new ApiError(
      'Sunucudan geçerli bir JSON yanıtı alınamadı.',
      response.status,
      'invalid_json'
    );
  }
}
