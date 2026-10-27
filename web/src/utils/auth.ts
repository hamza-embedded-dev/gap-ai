export const TOKEN_STORAGE_KEY = 'gap_access_token';
export const AUTH_SESSION_INVALID_EVENT = 'gap:auth-session-invalid';

/**
 * Reads stored Bearer token from browser localStorage.
 */
export function getStoredToken(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    if (!window.localStorage) return null;
    const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!token || !token.trim()) {
      return null;
    }
    return token.trim();
  } catch {
    return null;
  }
}

/**
 * Saves a valid Bearer token into localStorage.
 * Does not store null or whitespace-only strings.
 */
export function setStoredToken(token: string): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  if (typeof token !== 'string') {
    return false;
  }
  const trimmed = token.trim();
  if (!trimmed) {
    return false;
  }
  try {
    if (!window.localStorage) return false;
    window.localStorage.setItem(TOKEN_STORAGE_KEY, trimmed);
    return true;
  } catch {
    return false;
  }
}

/**
 * Clears stored token from localStorage.
 */
export function clearStoredToken(): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    if (!window.localStorage) return;
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Continue silently if storage access fails
  }
}

/**
 * Extracts `?t=` parameter from current window URL.
 * - If a valid token is found, persists it into localStorage.
 * - Sanitizes the address bar using `history.replaceState` while preserving
 *   other search query parameters and hash (#).
 * - If no `t` parameter is present, keeps existing stored token.
 *
 * @returns Active or newly captured token if available, otherwise null.
 */
export function extractTokenFromUrlAndClean(): string | null {
  if (typeof window === 'undefined' || !window.location) {
    return null;
  }

  try {
    const url = new URL(window.location.href);
    const hasTokenParam = url.searchParams.has('t');

    if (hasTokenParam) {
      const tokenValue = url.searchParams.get('t')?.trim();
      let tokenWasStored = false;

      if (tokenValue) {
        tokenWasStored = setStoredToken(tokenValue);
      }

      // Remove only the 't' parameter:
      url.searchParams.delete('t');

      const remainingQuery = url.searchParams.toString();
      const cleanSearch = remainingQuery ? `?${remainingQuery}` : '';
      const cleanUrl = `${url.pathname}${cleanSearch}${url.hash}`;

      window.history.replaceState(window.history.state, '', cleanUrl);

      if (tokenValue && tokenWasStored) {
        return tokenValue;
      }
    }
  } catch {
    // Return stored token on URL parsing failure
  }

  return getStoredToken();
}

/**
 * Detects OAuth error parameters in query or hash (e.g. user cancelled Google consent),
 * sanitizes the address bar, and returns an error description if present.
 */
export function extractOAuthErrorFromUrl(): string | null {
  if (typeof window === 'undefined' || !window.location) {
    return null;
  }
  try {
    const url = new URL(window.location.href);
    let error = url.searchParams.get('error');
    let errorDescription = url.searchParams.get('error_description');

    // Also check hash parameters: e.g. #error=access_denied&error_description=...
    if (!error && url.hash && url.hash.includes('error=')) {
      const hashParams = new URLSearchParams(url.hash.replace(/^#/, ''));
      error = hashParams.get('error');
      errorDescription = hashParams.get('error_description');
    }

    if (error) {
      // Remove error parameters from URL to keep address bar clean
      url.searchParams.delete('error');
      url.searchParams.delete('error_code');
      url.searchParams.delete('error_description');
      const cleanSearch = url.searchParams.toString() ? `?${url.searchParams.toString()}` : '';
      const cleanHash = url.hash && url.hash.includes('error=') ? '' : url.hash;
      const cleanUrl = `${url.pathname}${cleanSearch}${cleanHash}`;
      window.history.replaceState(window.history.state, '', cleanUrl);

      if (error === 'access_denied') {
        return 'Google sign-in was cancelled.';
      }
      return errorDescription || error || 'Authentication failed.';
    }
  } catch {
    // Ignore URL parse failures
  }
  return null;
}

