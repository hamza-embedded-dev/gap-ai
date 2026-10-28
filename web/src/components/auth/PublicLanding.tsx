import React from 'react';
import {
  Activity,
  BarChart2,
  Cpu,
  Mic,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { GoogleAuthButton } from './GoogleAuthButton';
import { isSupabaseConfigured } from '../../utils/supabase';

interface PublicLandingProps {
  onTryDemo: () => void;
  onExploreDemoAuth: () => void;
  onError?: (msg: string) => void;
  isLoading?: boolean;
}

export const PublicLanding: React.FC<PublicLandingProps> = ({
  onTryDemo,
  onExploreDemoAuth,
  onError,
  isLoading = false,
}) => {
  const configured = isSupabaseConfigured();

  return (
    <div className="public-landing-container" id="public-landing">
      {/* Hero Section */}
      <section className="card landing-hero-card">
        <div className="hero-content">
          <div className="badge badge-accent">AI-Powered Behavioral Assistant</div>
          <h2 className="hero-title">
            Intelligent Goal &amp; Action Planning with GAP Analysis
          </h2>
          <p className="hero-description">
            Bridge the intention-behavior gap. Plan your daily schedule with conversational AI,
            track real-world outcomes, and receive personalized coaching insights tailored to your habits.
          </p>

          <div className="hero-cta-group">
            <GoogleAuthButton
              label="Continue with Google"
              onError={onError}
              className="btn-primary-large"
            />

            <button
              id="landing-try-demo-btn"
              type="button"
              className="btn btn-secondary btn-large"
              onClick={onTryDemo}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  <span>Starting Demo...</span>
                </>
              ) : (
                'Start 24-Hour Demo'
              )}
            </button>

            <button
              type="button"
              className="btn btn-ghost"
              onClick={onExploreDemoAuth}
              id="landing-auth-details-btn"
            >
              Auth &amp; Architecture Details
            </button>
          </div>

          {!configured && (
            <p className="hero-notice">
              Note: Supabase Google OAuth requires VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.
              Use Start 24-Hour Demo for instantaneous preview.
            </p>
          )}
        </div>
      </section>

      {/* Feature Capabilities Grid */}
      <section className="landing-features-grid">
        <div className="feature-card">
          <div className="feature-icon-wrapper">
            <Mic className="feature-icon" aria-hidden="true" />
          </div>
          <h3>Voice &amp; Text Parsing</h3>
          <p>
            Speak or type naturally in English or Turkish. Groq Whisper and Nebius LLM transform
            spoken intent into structured, conflict-free plans in milliseconds.
          </p>
        </div>

        <div className="feature-card">
          <div className="feature-icon-wrapper">
            <BarChart2 className="feature-icon" aria-hidden="true" />
          </div>
          <h3>Deterministic GAP Analytics</h3>
          <p>
            Measure adherence percentages, delay patterns, and postponement trends without LLM hallucinations.
            Track your behavior objectively.
          </p>
        </div>

        <div className="feature-card">
          <div className="feature-icon-wrapper">
            <Zap className="feature-icon" aria-hidden="true" />
          </div>
          <h3>Contextual Coaching</h3>
          <p>
            Adaptive recommendations evaluate past performance and local weather context to suggest
            optimal execution windows.
          </p>
        </div>

        <div className="feature-card">
          <div className="feature-icon-wrapper">
            <Cpu className="feature-icon" aria-hidden="true" />
          </div>
          <h3>ESP32-S3 Hardware Sync</h3>
          <p>
            Embedded desk hardware with I2S microphone, audio amplifier, and OLED screen
            keeps you aligned even away from your browser.
          </p>
        </div>

        <div className="feature-card">
          <div className="feature-icon-wrapper">
            <ShieldCheck className="feature-icon" aria-hidden="true" />
          </div>
          <h3>Strict Data Isolation</h3>
          <p>
            Supabase Auth with Row Level Security (RLS) ensures your plans, history, and profile
            remain strictly confidential.
          </p>
        </div>

        <div className="feature-card">
          <div className="feature-icon-wrapper">
            <Activity className="feature-icon" aria-hidden="true" />
          </div>
          <h3>Offline Resilient</h3>
          <p>
            Idempotent request handling and localized session caching ensure zero duplicate plans
            during spotty network conditions.
          </p>
        </div>
      </section>
    </div>
  );
};
