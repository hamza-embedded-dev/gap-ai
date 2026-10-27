import React from 'react';
import { Lock, Sparkles } from 'lucide-react';
import { GoogleAuthButton } from './GoogleAuthButton';
import { isSupabaseConfigured } from '../../utils/supabase';

interface AuthRequiredCardProps {
  featureName?: string;
  onTryDemo?: () => void;
  onError?: (msg: string) => void;
}

export const AuthRequiredCard: React.FC<AuthRequiredCardProps> = ({
  featureName = 'this feature',
  onTryDemo,
  onError,
}) => {
  const configured = isSupabaseConfigured();

  return (
    <section className="card auth-required-card" id="auth-required-card">
      <div className="card-header">
        <div className="auth-card-title-group">
          <div className="auth-lock-icon" aria-hidden="true">
            <Lock className="w-5 h-5" />
          </div>
          <div>
            <h2>Sign in to Access {featureName}</h2>
            <p className="auth-subtitle">
              User-scoped data isolation protects your personal goals, schedules, and analytics.
            </p>
          </div>
        </div>
        <span className="status-pill pill-inactive">Sign-in Required</span>
      </div>

      <div className="auth-benefits-grid">
        <div className="benefit-item">
          <Sparkles className="benefit-icon" aria-hidden="true" />
          <div>
            <strong>Private &amp; Isolated:</strong>
            <p>Your plans and GAP performance analytics belong strictly to your account.</p>
          </div>
        </div>
        <div className="benefit-item">
          <Sparkles className="benefit-icon" aria-hidden="true" />
          <div>
            <strong>Hardware &amp; Voice Sync:</strong>
            <p>Voice-created plans and ESP32 hardware logs synchronize seamlessly.</p>
          </div>
        </div>
      </div>

      {!configured && (
        <div className="alert alert-warning" role="alert">
          <span>
            Supabase Auth environment variables are not configured on this instance.
            You can still test features using a 24-hour isolated Demo Session.
          </span>
        </div>
      )}

      <div className="auth-actions-row">
        <GoogleAuthButton
          label="Continue with Google"
          onError={onError}
          className="btn-large"
        />

        {onTryDemo && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onTryDemo}
            id="auth-try-demo-btn"
          >
            Try 24-Hour Demo
          </button>
        )}
      </div>
    </section>
  );
};
