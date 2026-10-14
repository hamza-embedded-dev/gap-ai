export const TOKEN_STORAGE_KEY = 'gap_access_token';

/**
 * Tarayıcı yerel deposundan kayıtlı Bearer token'ı okur.
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
 * Geçerli bir Bearer token'ı yerel depoya kaydeder.
 * Boş veya yalnızca boşluktan oluşan değerleri saklamaz.
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
 * Yerel depodaki token kaydını temizler.
 */
export function clearStoredToken(): void {
  if (typeof window === 'undefined' || !window.localStorage) {
    return;
  }
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Depolama erişim hatası durumunda sessizce devam et
  }
}

/**
 * URL'deki `?t=` parametresini okur.
 * - Geçerli bir token varsa yerel depoya kaydeder.
 * - Adres çubuğundaki diğer arama parametrelerini ve hash (#) kısmını bozmadan
 *   yalnızca `t` parametresini `history.replaceState` ile kaldırır.
 * - URL'de `t` yoksa mevcut kayıtlı token'ı korur.
 *
 * @returns Aktif veya yeni kaydedilen token (varsa), yoksa null.
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

      // Yalnızca 't' parametresini temizle:
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
    // URL parsing hatasında mevcut depolanmış token'a geri dön
  }

  return getStoredToken();
}
