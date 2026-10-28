import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Check,
  ClipboardList,
  Globe,
  KeyRound,
  Link2,
  Pencil,
  Server,
  ShieldCheck,
  Sparkles,
  User as UserIcon,
} from 'lucide-react';
import { createDemoSession } from './api/demo';
import { CreatePlan } from './pages/CreatePlan';
import { PlanList } from './pages/PlanList';
import {
  clearStoredToken,
  extractOAuthErrorFromUrl,
  extractTokenFromUrlAndClean,
  getStoredToken,
  setStoredToken,
} from './utils/auth';
import {
  getSupabaseSession,
  isSupabaseConfigured,
  onSupabaseAuthStateChange,
  signOutUser,
  type User,
} from './utils/supabase';
import { GoogleAuthButton } from './components/auth/GoogleAuthButton';
import { PublicLanding } from './components/auth/PublicLanding';
import { AuthRequiredCard } from './components/auth/AuthRequiredCard';
import { Insights } from './pages/Insights';
import { PersonalAICoach } from './pages/PersonalAICoach';
import { Profile } from './pages/Profile';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { AUTH_SESSION_INVALID_EVENT } from './api/client';
import './App.css';

type ActiveTab = 'overview' | 'insights' | 'coach' | 'plans' | 'create' | 'profile' | 'demo';

function App() {
  // Capture ?t= parameter on initial load or read stored token:
  const [token, setToken] = useState<string | null>(() => {
    return extractTokenFromUrlAndClean() || getStoredToken();
  });
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authMethod, setAuthMethod] = useState<'google' | 'demo' | 'token' | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>(() => {
    return (extractTokenFromUrlAndClean() || getStoredToken()) ? 'insights' : 'overview';
  });

  useEffect(() => {
    // Detect OAuth errors or cancellation in URL callback
    const oauthError = extractOAuthErrorFromUrl();
    if (oauthError) {
      setErrorMessage(oauthError);
    }

    // Check existing Supabase session
    let isMounted = true;
    void getSupabaseSession().then((session) => {
      if (!isMounted) return;
      if (session?.access_token) {
        setToken(session.access_token);
        setStoredToken(session.access_token);
        setAuthUser(session.user);
        setAuthMethod('google');
      } else if (getStoredToken()) {
        setAuthMethod('token');
      }
    });

    // Subscribe to Supabase Auth state changes
    const { data: authListener } = onSupabaseAuthStateChange((event, session) => {
      if (!isMounted) return;
      if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') {
        if (session?.access_token) {
          setToken(session.access_token);
          setStoredToken(session.access_token);
          setAuthUser(session.user);
          setAuthMethod('google');
          if (event === 'SIGNED_IN') {
            setSuccessMessage('Successfully signed in with Google.');
            setActiveTab('insights');
          }
        }
      } else if (event === 'SIGNED_OUT') {
        setToken(null);
        setAuthUser(null);
        setAuthMethod(null);
        clearStoredToken();
      }
    });

    const handleInvalidSession = () => {
      setToken(null);
      setAuthUser(null);
      setAuthMethod(null);
      setExpiresAt(null);
    };

    window.addEventListener(AUTH_SESSION_INVALID_EVENT, handleInvalidSession);
    return () => {
      isMounted = false;
      authListener?.subscription?.unsubscribe();
      window.removeEventListener(AUTH_SESSION_INVALID_EVENT, handleInvalidSession);
    };
  }, []);

  const handleTryDemo = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const session = await createDemoSession();
      if (!setStoredToken(session.token)) {
        throw new Error(
          'The session was created, but this browser could not save its access token. Enable browser storage and try again.'
        );
      }
      setToken(session.token);
      setExpiresAt(session.expires_at);
      setAuthMethod('demo');
      setSuccessMessage('Demo session created successfully and token saved.');
      setActiveTab('insights');
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : 'An unexpected error occurred while starting demo session.';
      setErrorMessage(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignOut = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      await signOutUser();
      setToken(null);
      setAuthUser(null);
      setAuthMethod(null);
      setExpiresAt(null);
      setActiveTab('overview');
      setSuccessMessage('Successfully signed out.');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error signing out.';
      setErrorMessage(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearSession = () => {
    clearStoredToken();
    setToken(null);
    setAuthUser(null);
    setAuthMethod(null);
    setExpiresAt(null);
    setErrorMessage(null);
    setSuccessMessage('Session cleared from local storage.');
  };

  const maskToken = (val: string) => {
    if (val.length <= 12) return val;
    return `${val.slice(0, 6)}...${val.slice(-6)}`;
  };

  const supabaseReady = isSupabaseConfigured();

  return (
    <ErrorBoundary>
      <div className="app-container">
        <header className="app-header">
          <div className="badge">GAP-AI • Web Client</div>
          <h1>Goal &amp; Action Planning</h1>
          <p className="app-subtitle">Personal Behavior &amp; Analytics Assistant</p>

          {/* User Auth Status Bar in Header */}
          <div className="app-header-auth-bar">
            {token ? (
              <div className="user-profile-chip" id="user-profile-chip">
                {authUser?.user_metadata?.avatar_url ? (
                  <img
                    src={authUser.user_metadata.avatar_url}
                    alt={authUser.user_metadata.full_name || 'User avatar'}
                    className="user-avatar-img"
                  />
                ) : (
                  <div className="user-avatar-placeholder" aria-hidden="true">
                    {(
                      authUser?.user_metadata?.full_name ||
                      authUser?.email ||
                      (authMethod === 'demo' ? 'D' : 'U')
                    )[0].toUpperCase()}
                  </div>
                )}
                <span
                  className="user-email-text"
                  title={authUser?.email || 'Authenticated Session'}
                >
                  {authUser?.user_metadata?.full_name ||
                    authUser?.email ||
                    (authMethod === 'demo' ? 'Demo Session (24h)' : 'Active Bearer Session')}
                </span>
                <button
                  id="header-sign-out-btn"
                  type="button"
                  className="btn-header-signout"
                  onClick={handleSignOut}
                  title="Sign out of current session"
                >
                  Sign Out
                </button>
              </div>
            ) : (
              <GoogleAuthButton
                label="Continue with Google"
                onError={(msg) => setErrorMessage(msg)}
              />
            )}
          </div>

          {/* Main Navigation Tabs */}
          <nav className="main-nav-tabs" role="tablist" aria-label="Main navigation">
            <button
              id="tab-overview-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'overview'}
              className={`nav-tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              <Globe className="tab-icon" aria-hidden="true" />
              <span>Overview</span>
            </button>
            <button
              id="tab-profile-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'profile'}
              className={`nav-tab-btn ${activeTab === 'profile' ? 'active' : ''}`}
              onClick={() => setActiveTab('profile')}
            >
              <UserIcon className="tab-icon" aria-hidden="true" />
              <span>Profile</span>
            </button>
            <button
              id="tab-insights-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'insights'}
              className={`nav-tab-btn ${activeTab === 'insights' ? 'active' : ''}`}
              onClick={() => setActiveTab('insights')}
            >
              <BarChart3 className="tab-icon" aria-hidden="true" />
              <span>Insights</span>
            </button>
            <button
              id="tab-coach-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'coach'}
              className={`nav-tab-btn ${activeTab === 'coach' ? 'active' : ''}`}
              onClick={() => setActiveTab('coach')}
            >
              <Sparkles className="tab-icon" aria-hidden="true" />
              <span>Personal AI Coach</span>
            </button>
            <button
              id="tab-plan-list-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'plans'}
              className={`nav-tab-btn ${activeTab === 'plans' ? 'active' : ''}`}
              onClick={() => setActiveTab('plans')}
            >
              <ClipboardList className="tab-icon" aria-hidden="true" />
              <span>My Plans</span>
            </button>
            <button
              id="tab-create-plan-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'create'}
              className={`nav-tab-btn ${activeTab === 'create' ? 'active' : ''}`}
              onClick={() => setActiveTab('create')}
            >
              <Pencil className="tab-icon" aria-hidden="true" />
              <span>Create Plan</span>
            </button>
            <button
              id="tab-demo-btn"
              type="button"
              role="tab"
              aria-selected={activeTab === 'demo'}
              className={`nav-tab-btn ${activeTab === 'demo' ? 'active' : ''}`}
              onClick={() => setActiveTab('demo')}
            >
              <KeyRound className="tab-icon" aria-hidden="true" />
              <span>Demo &amp; Auth</span>
              {token && <span className="tab-pill">Active</span>}
            </button>
          </nav>
        </header>

        <main className="app-main">
          {/* Notification Alerts */}
          {errorMessage && (
            <div className="alert alert-error" role="alert" id="error-alert">
              <AlertTriangle className="alert-icon" aria-hidden="true" />
              <span>{errorMessage}</span>
            </div>
          )}

          {successMessage && (
            <div className="alert alert-success" role="status" id="success-alert">
              <Check className="alert-icon" aria-hidden="true" />
              <span>{successMessage}</span>
            </div>
          )}

          {/* Public Overview / Landing Tab */}
          {activeTab === 'overview' && (
            <PublicLanding
              token={token}
              onTryDemo={handleTryDemo}
              onExploreDemoAuth={() => setActiveTab('demo')}
              onError={(msg) => setErrorMessage(msg)}
              isLoading={isLoading}
            />
          )}

          {/* Insights Analytics Tab */}
          {activeTab === 'insights' && (
            token ? (
              <Insights token={token} onRequireAuth={() => setActiveTab('demo')} />
            ) : (
              <AuthRequiredCard
                featureName="Insights & Analytics"
                onTryDemo={handleTryDemo}
                onError={(msg) => setErrorMessage(msg)}
              />
            )
          )}

          {/* Personal AI Coach Tab */}
          {activeTab === 'coach' && (
            token ? (
              <PersonalAICoach token={token} onRequireAuth={() => setActiveTab('demo')} />
            ) : (
              <AuthRequiredCard
                featureName="Personal AI Coach"
                onTryDemo={handleTryDemo}
                onError={(msg) => setErrorMessage(msg)}
              />
            )
          )}

          {/* My Plans Tab */}
          {activeTab === 'plans' && (
            token ? (
              <PlanList
                token={token}
                onRequireToken={() => setActiveTab('demo')}
                onNavigateCreate={() => setActiveTab('create')}
              />
            ) : (
              <AuthRequiredCard
                featureName="My Plans"
                onTryDemo={handleTryDemo}
                onError={(msg) => setErrorMessage(msg)}
              />
            )
          )}

          {/* Create Plan Tab */}
          {activeTab === 'create' && (
            token ? (
              <CreatePlan
                token={token}
                onRequireToken={() => setActiveTab('demo')}
                onNavigatePlans={() => setActiveTab('plans')}
              />
            ) : (
              <AuthRequiredCard
                featureName="Create Plan"
                onTryDemo={handleTryDemo}
                onError={(msg) => setErrorMessage(msg)}
              />
            )
          )}

          {/* Profile Tab */}
          {activeTab === 'profile' && (
            token ? (
              <Profile token={token} />
            ) : (
              <AuthRequiredCard
                featureName="User Profile"
                onTryDemo={handleTryDemo}
                onError={(msg) => setErrorMessage(msg)}
              />
            )
          )}

          {/* Demo & Authentication Tab */}
          {activeTab === 'demo' && (
            <>
              {/* Google OAuth Section */}
              <section className="card oauth-card" id="google-oauth-section">
                <div className="card-header">
                  <h2>Google OAuth 2.0 (Supabase Auth)</h2>
                  <span
                    id="oauth-status-badge"
                    className={`status-pill ${
                      authMethod === 'google' ? 'pill-active' : 'pill-inactive'
                    }`}
                  >
                    {authMethod === 'google' ? 'Google Active' : 'Not Connected'}
                  </span>
                </div>
                <p className="card-desc">
                  Sign in with your Google account using Supabase Auth. Sessions persist across
                  refreshes with automatic JWT rotation, securing personal plans and analytics.
                </p>

                <div className="action-row">
                  {!token ? (
                    <GoogleAuthButton
                      label="Continue with Google"
                      onError={(msg) => setErrorMessage(msg)}
                      className="btn-large"
                    />
                  ) : authMethod === 'google' ? (
                    <button
                      id="oauth-signout-btn"
                      type="button"
                      className="btn btn-secondary"
                      onClick={handleSignOut}
                      disabled={isLoading}
                    >
                      Sign Out of Google
                    </button>
                  ) : null}
                </div>

                {!supabaseReady && (
                  <div className="alert alert-warning" role="alert" style={{ marginTop: '12px' }}>
                    <span>
                      Supabase environment variables (<code>VITE_SUPABASE_URL</code> and{' '}
                      <code>VITE_SUPABASE_ANON_KEY</code>) are not configured. To test live Google
                      sign-in, configure them in your Netlify or local environment.
                    </span>
                  </div>
                )}

                {authMethod === 'google' && authUser && (
                  <div className="token-info-panel" id="google-user-panel" style={{ marginTop: '12px' }}>
                    <div className="info-item">
                      <span className="label">Account Name:</span>
                      <span className="value">
                        {authUser.user_metadata?.full_name || authUser.user_metadata?.name || 'Google User'}
                      </span>
                    </div>
                    <div className="info-item">
                      <span className="label">Account Email:</span>
                      <span className="value">{authUser.email || 'N/A'}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">User UUID:</span>
                      <code className="token-code">{maskToken(authUser.id)}</code>
                    </div>
                    <div className="info-item">
                      <span className="label">Provider:</span>
                      <span className="value">Google OAuth 2.0 (Supabase)</span>
                    </div>
                  </div>
                )}
              </section>

              {/* Demo Session & Authorization Section */}
              <section className="card demo-card">
                <div className="card-header">
                  <h2>Demo Session &amp; Authorization</h2>
                  <span
                    id="token-status-badge"
                    className={`status-pill ${token ? 'pill-active' : 'pill-inactive'}`}
                  >
                    {token ? 'Active Session' : 'No Active Session'}
                  </span>
                </div>
                <p className="card-desc">
                  Call the <code>POST /demo/session</code> endpoint on the local backend to receive
                  an isolated 24-hour demo token, or authenticate via the URL parameter{' '}
                  <code>?t=&lt;token&gt;</code>.
                </p>

                <div className="action-row">
                  <button
                    id="try-demo-btn"
                    type="button"
                    className="btn btn-primary"
                    onClick={handleTryDemo}
                    disabled={isLoading}
                  >
                    {isLoading ? (
                      <>
                        <span className="spinner" aria-hidden="true"></span>
                        <span>Connecting...</span>
                      </>
                    ) : (
                      'Try Demo'
                    )}
                  </button>

                  {token && (
                    <button
                      id="clear-session-btn"
                      type="button"
                      className="btn btn-secondary"
                      onClick={handleClearSession}
                      disabled={isLoading}
                    >
                      Reset Session
                    </button>
                  )}
                </div>

                {/* Active Token Information Panel */}
                {token && (
                  <div className="token-info-panel" id="active-token-panel">
                    <div className="info-item">
                      <span className="label">Active Bearer Token:</span>
                      <code className="token-code" title={token}>
                        {maskToken(token)}
                      </code>
                    </div>
                    {expiresAt && (
                      <div className="info-item">
                        <span className="label">Expires At:</span>
                        <span className="value">
                          {new Date(expiresAt).toLocaleString('en-US')}
                        </span>
                      </div>
                    )}
                    <div className="info-item">
                      <span className="label">Storage:</span>
                      <span className="value">localStorage (gap_access_token)</span>
                    </div>
                    <div className="info-item">
                      <span className="label">Type:</span>
                      <span className="value">
                        {authMethod === 'google'
                          ? 'Supabase JWT'
                          : authMethod === 'demo'
                          ? '24-hour Demo Token'
                          : 'Custom Token'}
                      </span>
                    </div>
                  </div>
                )}
              </section>

              {/* Architecture & Verification Card */}
              <section className="card info-card">
                <h2>Session and API Security</h2>
                <ul className="feature-list">
                  <li>
                    <ShieldCheck className="check" aria-hidden="true" />
                    <span>
                      <strong>Secure sessions:</strong> Access tokens are stored locally and sent with authenticated requests.
                    </span>
                  </li>
                  <li>
                    <Link2 className="check" aria-hidden="true" />
                    <span>
                      <strong>Secure sign-in links:</strong> Access tokens in the <code>?t=</code> parameter are saved and removed from the address bar.
                    </span>
                  </li>
                  <li>
                    <Server className="check" aria-hidden="true" />
                    <span>
                      <strong>Private API access:</strong> Protected requests require a valid session token.
                    </span>
                  </li>
                </ul>
              </section>
            </>
          )}
        </main>

        <footer className="app-footer">
          <p>GAP-AI • 2026</p>
        </footer>
      </div>
    </ErrorBoundary>
  );
}

export default App;
