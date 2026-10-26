import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Check,
  ClipboardList,
  KeyRound,
  Link2,
  Pencil,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { createDemoSession } from './api/demo';
import { CreatePlan } from './pages/CreatePlan';
import { PlanList } from './pages/PlanList';
import {
  clearStoredToken,
  extractTokenFromUrlAndClean,
  getStoredToken,
  setStoredToken,
} from './utils/auth';
import { Insights } from './pages/Insights';
import { Profile } from './pages/Profile';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { AUTH_SESSION_INVALID_EVENT } from './api/client';
import './App.css';

type ActiveTab = 'insights' | 'plans' | 'create' | 'profile' | 'demo';

function App() {
  // Capture ?t= parameter on initial load or read stored token:
  const [token, setToken] = useState<string | null>(() => {
    return extractTokenFromUrlAndClean() || getStoredToken();
  });
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('insights');

  useEffect(() => {
    const handleInvalidSession = () => {
      setToken(null);
      setExpiresAt(null);
    };

    window.addEventListener(AUTH_SESSION_INVALID_EVENT, handleInvalidSession);
    return () => window.removeEventListener(AUTH_SESSION_INVALID_EVENT, handleInvalidSession);
  }, []);

  const handleTryDemo = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const session = await createDemoSession();
      if (!setStoredToken(session.token)) {
        throw new Error('The session was created, but this browser could not save its access token. Enable browser storage and try again.');
      }
      setToken(session.token);
      setExpiresAt(session.expires_at);
      setSuccessMessage('Demo session created successfully and token saved.');
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

  const handleClearSession = () => {
    clearStoredToken();
    setToken(null);
    setExpiresAt(null);
    setErrorMessage(null);
    setSuccessMessage('Session cleared from local storage.');
  };

  const maskToken = (val: string) => {
    if (val.length <= 12) return val;
    return `${val.slice(0, 6)}...${val.slice(-6)}`;
  };

  return (
    <ErrorBoundary>
      <div className="app-container">
        <header className="app-header">
          <div className="badge">GAP-AI • Web Client</div>
          <h1>Goal &amp; Action Planning</h1>
          <p className="app-subtitle">Personal Behavior &amp; Analytics Assistant</p>

          {/* Main Navigation Tabs */}
          <nav className="main-nav-tabs" role="tablist" aria-label="Main navigation">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'profile'}
              className={`nav-tab-btn ${activeTab === 'profile' ? 'active' : ''}`}
              onClick={() => setActiveTab('profile')}
            >Profile</button>
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

          {/* Insights Analytics Tab */}
          {activeTab === 'insights' && (
            <Insights token={token} onRequireAuth={() => setActiveTab('demo')} />
          )}

          {activeTab === 'plans' && (
            <PlanList
              token={token}
              onRequireToken={() => setActiveTab('demo')}
              onNavigateCreate={() => setActiveTab('create')}
            />
          )}

          {activeTab === 'create' && (
            <CreatePlan
              token={token}
              onRequireToken={() => setActiveTab('demo')}
              onNavigatePlans={() => setActiveTab('plans')}
            />
          )}

          {activeTab === 'profile' && <Profile token={token} />}

          {/* Demo & Authentication Tab */}
          {activeTab === 'demo' && (
            <>
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
