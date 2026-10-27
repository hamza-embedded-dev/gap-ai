import { createClient, type Session, type SupabaseClient, type User } from '@supabase/supabase-js';
import { clearStoredToken } from './auth.ts';

const rawUrl = (
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_SUPABASE_URL) ||
  ''
).trim();

const rawAnonKey = (
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_SUPABASE_ANON_KEY) ||
  ''
).trim();

export const isSupabaseConfigured = (): boolean => {
  return Boolean(
    rawUrl &&
    rawAnonKey &&
    (rawUrl.startsWith('https://') || rawUrl.startsWith('http://'))
  );
};

export const supabase: SupabaseClient | null = isSupabaseConfigured()
  ? createClient(rawUrl, rawAnonKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    })
  : null;

/**
 * Validates post-login redirect URL to prevent open-redirect vulnerabilities.
 * Only allows exact matching origin or trusted application domains.
 */
export function validateRedirectUrl(candidateUrl?: string): string {
  if (typeof window === 'undefined') {
    return 'https://gap-ai-demo.netlify.app';
  }
  const currentOrigin = window.location.origin;
  if (!candidateUrl) {
    return currentOrigin;
  }
  try {
    const parsed = new URL(candidateUrl, currentOrigin);
    const allowedOrigins = [
      currentOrigin,
      'https://gap-ai-demo.netlify.app',
      'http://localhost:5173',
      'http://127.0.0.1:5173',
      'http://localhost:3000',
    ];
    if (allowedOrigins.includes(parsed.origin)) {
      return parsed.toString();
    }
  } catch {
    // Safe fallback to current origin on parse error
  }
  return currentOrigin;
}

/**
 * Initiates Google OAuth sign-in flow through Supabase Auth.
 */
export async function signInWithGoogle(redirectPath?: string) {
  if (!isSupabaseConfigured() || !supabase) {
    return {
      data: null,
      error: new Error(
        'Supabase Auth is not configured. Please set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in your environment.'
      ),
    };
  }

  const origin = typeof window !== 'undefined' ? window.location.origin : 'https://gap-ai-demo.netlify.app';
  const targetUrl = redirectPath
    ? `${origin}${redirectPath.startsWith('/') ? redirectPath : `/${redirectPath}`}`
    : origin;

  const redirectTo = validateRedirectUrl(targetUrl);

  try {
    const response = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo,
        queryParams: {
          access_type: 'offline',
          prompt: 'consent',
        },
      },
    });
    return response;
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to initiate Google sign-in.';
    return {
      data: null,
      error: new Error(msg),
    };
  }
}

/**
 * Signs out current user from Supabase session and clears stored tokens.
 */
export async function signOutUser() {
  if (supabase) {
    try {
      await supabase.auth.signOut();
    } catch {
      // Continue to wipe local state regardless of server response
    }
  }
  clearStoredToken();
  return { error: null };
}

/**
 * Retrieves the currently active Supabase Auth session if available.
 */
export async function getSupabaseSession(): Promise<Session | null> {
  if (!supabase) return null;
  try {
    const { data } = await supabase.auth.getSession();
    return data.session;
  } catch {
    return null;
  }
}

/**
 * Subscribes to Supabase Auth state changes (sign in, sign out, token refresh).
 */
export function onSupabaseAuthStateChange(
  callback: (event: string, session: Session | null) => void
) {
  if (!supabase) {
    return { data: { subscription: { unsubscribe: () => {} } } };
  }
  return supabase.auth.onAuthStateChange(callback);
}

export type { Session, User };
