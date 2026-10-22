import { getStoredToken } from '../utils/auth';

/**
 * Base API URL read from environment; defaults to Vite dev proxy '/api'.
 */
const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '');

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
 * GAP-AI backend API client.
 * - Automatically attaches `Authorization: Bearer <token>` header if a token is stored.
 * - Sets `Content-Type: application/json` for non-FormData request payloads.
 * - Throws structured `ApiError` instances on HTTP and network failures.
 */
export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = `${API_BASE}${normalizedEndpoint}`;

  const headers = new Headers(options.headers || {});

  // Attach stored Bearer token if present:
  const token = getStoredToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  // Set JSON Content-Type if body is present and not FormData:
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
    const originalMessage = err instanceof Error ? err.message : 'Network error';
    throw new ApiError(
      `Unable to connect to server (${originalMessage}). Please ensure the backend service is running.`,
      0,
      'network_error'
    );
  }

  // Parse HTTP error status codes:
  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText || 'Unknown error'}`;
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
      // If response body is not JSON, default to status text.
    }

    throw new ApiError(errorMessage, response.status, errorType);
  }

  // Handle 204 No Content or empty responses:
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
      'Failed to parse JSON response from server.',
      response.status,
      'invalid_json'
    );
  }
}
