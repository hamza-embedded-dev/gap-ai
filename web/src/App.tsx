import { useState } from 'react';
import { createDemoSession } from './api/demo';
import {
  clearStoredToken,
  extractTokenFromUrlAndClean,
  getStoredToken,
  setStoredToken,
} from './utils/auth';
import { Insights } from './pages/Insights';
import './App.css';

type ActiveTab = 'insights' | 'demo';

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

        {/* Ana Navigasyon Sekmeleri */}
        <nav className="main-nav-tabs" aria-label="Ana Sayfa Sekmeleri">
          <button
            id="tab-insights-btn"
            type="button"
            className={`nav-tab-btn ${activeTab === 'insights' ? 'active' : ''}`}
            onClick={() => setActiveTab('insights')}
          >
            <span className="tab-icon" aria-hidden="true">📊</span>
            <span>Analiz (Insights)</span>
          </button>
          <button
            id="tab-demo-btn"
            type="button"
            className={`nav-tab-btn ${activeTab === 'demo' ? 'active' : ''}`}
            onClick={() => setActiveTab('demo')}
          >
            <span className="tab-icon" aria-hidden="true">🔑</span>
            <span>Demo &amp; Yetki</span>
            {token && <span className="tab-pill">Aktif</span>}
          </button>
        </nav>
      </header>

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

        {/* Analiz (Insights) Sekmesi */}
        {activeTab === 'insights' && <Insights />}

        {/* Demo ve Kimlik Doğrulama Kartı */}
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
