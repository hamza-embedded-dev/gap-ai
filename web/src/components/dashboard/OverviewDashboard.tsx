import React from 'react';
import {
  BarChart3,
  CheckCircle2,
  ClipboardList,
  Pencil,
  Sparkles,
} from 'lucide-react';
import { WeatherCard } from '../weather/WeatherCard';
import type { User } from '../../utils/supabase';
import './OverviewDashboard.css';

interface OverviewDashboardProps {
  token: string;
  authUser?: User | null;
  authMethod?: 'google' | 'demo' | 'token' | null;
  onNavigate: (tab: 'insights' | 'coach' | 'plans' | 'create' | 'profile' | 'demo') => void;
}

export const OverviewDashboard: React.FC<OverviewDashboardProps> = ({
  token,
  authUser,
  authMethod,
  onNavigate,
}) => {
  const displayName = authUser?.user_metadata?.full_name || authUser?.email || 'Planner';
  const isDemo = authMethod === 'demo';

  return (
    <div className="overview-dashboard" id="overview-dashboard">
      {/* Welcome & Session Card */}
      <section className="overview-welcome-card" id="overview-welcome-card">
        <div className="overview-welcome-header">
          <div className="overview-welcome-title-group">
            <h1 className="overview-welcome-title" id="overview-welcome-title">
              Welcome back, {displayName}!
            </h1>
            <p className="overview-welcome-subtitle">
              Plan your day, track real-world outcomes, and view live local weather context.
            </p>
          </div>
          <span className="overview-session-badge" id="overview-session-badge">
            <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
            <span>{isDemo ? '24h Demo Active' : 'Session Active'}</span>
          </span>
        </div>
      </section>

      {/* Prominent Local Weather Card */}
      <section id="overview-weather-section" aria-label="Local Weather Forecast">
        <WeatherCard token={token} />
      </section>

      {/* Quick Navigation Cards Grid */}
      <section className="overview-quick-actions" aria-label="Quick Actions">
        <button
          type="button"
          id="overview-action-plans"
          className="overview-action-card"
          onClick={() => onNavigate('plans')}
        >
          <div className="overview-action-icon-wrapper action-icon-plans">
            <ClipboardList className="w-5 h-5" aria-hidden="true" />
          </div>
          <h2 className="overview-action-title">My Plans</h2>
          <p className="overview-action-desc">
            Review your scheduled activities, record completion outcomes, and track punctuality.
          </p>
        </button>

        <button
          type="button"
          id="overview-action-create"
          className="overview-action-card"
          onClick={() => onNavigate('create')}
        >
          <div className="overview-action-icon-wrapper action-icon-create">
            <Pencil className="w-5 h-5" aria-hidden="true" />
          </div>
          <h2 className="overview-action-title">Create Plan</h2>
          <p className="overview-action-desc">
            Add a new plan using conversational AI text parsing or ESP32 voice input.
          </p>
        </button>

        <button
          type="button"
          id="overview-action-insights"
          className="overview-action-card"
          onClick={() => onNavigate('insights')}
        >
          <div className="overview-action-icon-wrapper action-icon-insights">
            <BarChart3 className="w-5 h-5" aria-hidden="true" />
          </div>
          <h2 className="overview-action-title">Behavior Insights</h2>
          <p className="overview-action-desc">
            Measure adherence percentages, postponement patterns, and activity distribution.
          </p>
        </button>

        <button
          type="button"
          id="overview-action-coach"
          className="overview-action-card"
          onClick={() => onNavigate('coach')}
        >
          <div className="overview-action-icon-wrapper action-icon-coach">
            <Sparkles className="w-5 h-5" aria-hidden="true" />
          </div>
          <h2 className="overview-action-title">Personal AI Coach</h2>
          <p className="overview-action-desc">
            Get adaptive recommendations tailored to your past habits and weather forecast.
          </p>
        </button>
      </section>
    </div>
  );
};

export default OverviewDashboard;
