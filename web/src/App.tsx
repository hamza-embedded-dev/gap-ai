import { useState } from 'react';
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
import './App.css';

type ActiveTab = 'insights' | 'plans' | 'create' | 'demo';

function App() {
// Sayfa ilk yüklendiğinde URL'deki ?t= parametresini yakala veya kayıtlı token'ı oku:
  const [token, setToken] = useState<string | null>(() => {
    return extractTokenFromUrlAndClean() || getStoredToken();
  });
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('insights');

  const handleTryDemo = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const session = await createDemoSession();
      setStoredToken(session.token);
      setToken(session.token);
      setExpiresAt(session.expires_at);
      setSuccessMessage('Demo oturumu başarıyla oluşturuldu ve token kaydedildi.');
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : 'Demo oturumu başlatılırken beklenmeyen bir hata oluştu.';
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
    setSuccessMessage('Oturum bilgisi yerel depodan temizlendi.');
  };

  const maskToken = (val: string) => {
    if (val.length <= 12) return val;
    return `${val.slice(0, 6)}...${val.slice(-6)}`;
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="badge">GAP-AI • Web Client</div>
        <h1>Hedef &amp; Eylem Planlama</h1>
        <p className="app-subtitle">Kişisel Davranış ve Analiz Asistanı</p>
      </header>

      {/* Navigasyon Sekmeleri */}
      <nav className="nav-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          id="tab-insights"
          aria-selected={activeTab === 'insights'}
          className={`nav-tab-btn ${activeTab === 'insights' ? 'nav-tab-active' : ''}`}
          onClick={() => setActiveTab('insights')}
        >
          📊 Analiz (Insights)
        </button>
        <button
          type="button"
          role="tab"
          id="tab-plan-list"
          aria-selected={activeTab === 'plans'}
          className={`nav-tab-btn ${activeTab === 'plans' ? 'nav-tab-active' : ''}`}
          onClick={() => setActiveTab('plans')}
        >
          📋 Planlarım (W1-3)
        </button>
        <button
          type="button"
          role="tab"
          id="tab-create-plan"
          aria-selected={activeTab === 'create'}
          className={`nav-tab-btn ${activeTab === 'create' ? 'nav-tab-active' : ''}`}
          onClick={() => setActiveTab('create')}
        >
          ✍️ Plan Oluştur (W1-2)
        </button>
        <button
          type="button"
          role="tab"
          id="tab-demo-session"
          aria-selected={activeTab === 'demo'}
          className={`nav-tab-btn ${activeTab === 'demo' ? 'nav-tab-active' : ''}`}
          onClick={() => setActiveTab('demo')}
        >
          🔑 Demo &amp; Oturum (W1-1)
        </button>
      </nav>

      <main className="app-main">
        {/* Bildirim Alanları */}
        {errorMessage && (
          <div className="alert alert-error" role="alert" id="error-alert">
            <span className="alert-icon">⚠️</span>
            <span>{errorMessage}</span>
          </div>
        )}

        {successMessage && (
          <div className="alert alert-success" role="status" id="success-alert">
            <span className="alert-icon">✓</span>
            <span>{successMessage}</span>
          </div>
        )}

        {/* Analiz ekranı */}
        {activeTab === 'insights' && <Insights />}

        {/* Plan listesi ve sonuç bildirme */}
        {activeTab === 'plans' && (
          <PlanList
            token={token}
            onRequireToken={() => setActiveTab('demo')}
            onNavigateCreate={() => setActiveTab('create')}
          />
        )}

        {/* Plan oluşturma */}
        {activeTab === 'create' && (
          <CreatePlan
            token={token}
            onRequireToken={() => setActiveTab('demo')}
          />
        )}

        {/* Demo ve kimlik doğrulama */}
        {activeTab === 'demo' && (
          <>
            <section className="card demo-card">
              <div className="card-header">
                <h2>Demo Oturumu ve Yetkilendirme</h2>
                <span
                  id="token-status-badge"
                  className={`status-pill ${token ? 'pill-active' : 'pill-inactive'}`}
                >
                  {token ? 'Oturum Açık' : 'Oturum Yok'}
                </span>
              </div>

              <p className="card-desc">
                Yerel backend üzerindeki <code>POST /demo/session</code> uç noktasını çağırarak
                24 saat geçerli izole bir demo token'ı alabilir veya URL üzerinden{' '}
                <code>?t=&lt;token&gt;</code> parametresiyle giriş yapabilirsiniz.
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
                      <span>Bağlanıyor...</span>
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
                    Oturumu Sıfırla
                  </button>
                )}
              </div>

              {/* Aktif Token Bilgi Paneli */}
              {token && (
                <div className="token-info-panel" id="active-token-panel">
                  <div className="info-item">
                    <span className="label">Aktif Bearer Token:</span>
                    <code className="token-code" title={token}>
                      {maskToken(token)}
                    </code>
                  </div>
                  {expiresAt && (
                    <div className="info-item">
                      <span className="label">Bitiş Zamanı:</span>
                      <span className="value">
                        {new Date(expiresAt).toLocaleString('tr-TR')}
                      </span>
                    </div>
                  )}
                  <div className="info-item">
                    <span className="label">Depolama:</span>
                    <span className="value">localStorage (gap_access_token)</span>
                  </div>
                </div>
              )}
            </section>

            {/* Mimari Durum Kartı */}
            <section className="card info-card">
              <h2>İskelet ve API İstemci Doğrulamaları</h2>
              <ul className="feature-list">
                <li>
                  <span className="check">✓</span>
                  <span>
                    <strong>Bearer Token Yönetimi:</strong> Kayıtlı token korumalı API isteklerine otomatik eklenir.
                  </span>
                </li>
                <li>
                  <span className="check">✓</span>
                  <span>
                    <strong>URL Parametre Temizleme:</strong> <code>?t=</code> parametresi okunur ve diğer parametreler/hash korunarak <code>history.replaceState</code> ile temizlenir.
                  </span>
                </li>
                <li>
                  <span className="check">✓</span>
                  <span>
                    <strong>Backend Proxy:</strong> Vite dev server <code>/api</code> isteklerini yerel backend'e vekilleştirir.
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
  );
}

export default App;
