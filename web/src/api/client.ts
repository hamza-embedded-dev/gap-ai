import {
  AUTH_SESSION_INVALID_EVENT,
  clearStoredToken,
  getStoredToken,
} from '../utils/auth.ts';

export { AUTH_SESSION_INVALID_EVENT };

/**
 * Base API URL read from environment; defaults to Vite dev proxy '/api'.
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
    const isAbort =
      (err instanceof Error && (err.name === 'AbortError' || err.name === 'TimeoutError')) ||
      (typeof DOMException !== 'undefined' &&
        err instanceof DOMException &&
        (err.name === 'AbortError' || err.name === 'TimeoutError')) ||
      Boolean(options.signal?.aborted);

    if (isAbort) {
      throw new ApiError(
        `Request timed out (${originalMessage}). The server took too long to respond.`,
        408,
        'timeout_error'
      );
    }

    throw new ApiError(
      `Unable to connect to server (${originalMessage}). Please ensure the backend service is running.`,
      0,
      'network_error'
    );
  }

  // Parse HTTP error status codes:
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      clearStoredToken();
      window.dispatchEvent(new Event(AUTH_SESSION_INVALID_EVENT));
    }

    let errorMessage = `HTTP ${response.status}: ${response.statusText || 'Unknown error'}`;
    let errorType = 'http_error';

    try {
      const errorJson = (await response.json()) as Record<string, unknown>;
      if (typeof errorJson.message === 'string' && errorJson.message.trim()) {
        errorMessage = errorJson.message.trim();
      } else if (errorJson.detail !== undefined && errorJson.detail !== null) {
        if (typeof errorJson.detail === 'string') {
          errorMessage = errorJson.detail.trim();
        } else if (Array.isArray(errorJson.detail)) {
          // Format FastAPI / Pydantic validation error objects: [{ loc, msg, type }]
          const formatted = errorJson.detail
            .map((item: unknown) => {
              if (typeof item === 'string') return item;
              if (item && typeof item === 'object') {
                const rec = item as Record<string, unknown>;
                const loc = Array.isArray(rec.loc)
                  ? rec.loc.filter((l) => l !== 'body').join('.')
                  : '';
                const msg = rec.msg ? String(rec.msg) : JSON.stringify(rec);
                return loc ? `${loc}: ${msg}` : msg;
              }
              return String(item);
            })
            .join('; ');
          if (formatted) errorMessage = formatted;
        } else if (typeof errorJson.detail === 'object') {
          errorMessage = JSON.stringify(errorJson.detail);
        }
      }
      if (typeof errorJson.error === 'string' && errorJson.error.trim()) {
        errorType = errorJson.error.trim();
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
