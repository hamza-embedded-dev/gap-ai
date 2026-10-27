import React, { useState } from 'react';
import { isSupabaseConfigured, signInWithGoogle } from '../../utils/supabase';

interface GoogleAuthButtonProps {
  onSuccess?: () => void;
  onError?: (message: string) => void;
  className?: string;
  label?: string;
}

export const GoogleAuthButton: React.FC<GoogleAuthButtonProps> = ({
  onError,
  className = '',
  label = 'Continue with Google',
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const configured = isSupabaseConfigured();

  const handleClick = async () => {
    setIsLoading(true);
    try {
      const { error } = await signInWithGoogle();
      if (error) {
        onError?.(error.message);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Google sign-in failed.';
      onError?.(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <button
      id="google-auth-btn"
      type="button"
      className={`btn-google-auth ${className}`}
      onClick={handleClick}
      disabled={isLoading || !configured}
      title={
        configured
          ? 'Sign in with your Google account'
          : 'Supabase Auth is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.'
      }
      aria-label="Continue with Google"
    >
      {isLoading ? (
        <>
          <span className="spinner" aria-hidden="true" />
          <span>Connecting to Google...</span>
        </>
      ) : (
        <>
          <svg
            className="google-icon"
            viewBox="0 0 24 24"
            width="20"
            height="20"
            aria-hidden="true"
          >
            <path
              fill="#4285F4"
              d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.17z"
            />
            <path
              fill="#34A853"
              d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.33 24 12 24z"
            />
            <path
              fill="#FBBC05"
              d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 10.04 0 12s.45 3.82 1.25 5.42l4.03-3.15z"
            />
            <path
              fill="#EA4335"
              d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
            />
          </svg>
          <span className="google-text">{label}</span>
        </>
      )}
    </button>
  );
};
