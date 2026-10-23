export const TOKEN_STORAGE_KEY = 'gap_access_token';

/**
 * Reads stored Bearer token from browser localStorage.
 */
export function getStoredToken(): string | null {
  if (typeof window === 'undefined' || !window.localStorage) {
    return null;
  }
  try {
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
  if (typeof window === 'undefined' || !window.localStorage) {
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
  if (typeof window === 'undefined' || !window.localStorage) {
    return;
  }
  try {
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

      if (tokenValue) {
        setStoredToken(tokenValue);
      }

      // Remove only the 't' parameter:
      url.searchParams.delete('t');

      const remainingQuery = url.searchParams.toString();
      const cleanSearch = remainingQuery ? `?${remainingQuery}` : '';
      const cleanUrl = `${url.pathname}${cleanSearch}${url.hash}`;

      window.history.replaceState(window.history.state, '', cleanUrl);

      if (tokenValue) {
        return tokenValue;
      }
    }
  } catch {
    // Return stored token on URL parsing failure
  }

  return getStoredToken();
}
