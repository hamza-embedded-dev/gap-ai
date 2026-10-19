import { useState } from 'react';
import { createPlan, parseNaturalLanguagePlan } from '../api/plans';
import type { ParsedPlan, Plan, PlanCategory } from '../types/plan';
import { generateIdempotencyKey } from '../utils/idempotency';
import './CreatePlan.css';

interface CreatePlanProps {
  token: string | null;
  onRequireToken?: () => void;
}

export function CreatePlan({ token, onRequireToken }: CreatePlanProps) {
  // Input and flow states
  const [inputText, setInputText] = useState<string>('');
  const [clarifyReply, setClarifyReply] = useState<string>('');
  const [parsedPlan, setParsedPlan] = useState<ParsedPlan | null>(null);
  const [savedPlan, setSavedPlan] = useState<Plan | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);

  // Loading & status states
  const [isParsing, setIsParsing] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Controlled mock mode (default: false / Live API)
  const [mockMode, setMockMode] = useState<boolean>(false);

  // Inline edit state for confirmation
  const [isEditing, setIsEditing] = useState<boolean>(false);

  // Quick sample templates
  const SAMPLE_PROMPTS = [
    { label: '🏃 Yarın 18:00 Koşu', text: "Yarın saat 18:00'de Belgrad Ormanı'nda 1 saat tempolu koşu yapacağım." },
    { label: '📚 Bu Cuma Kodlama', text: 'Bu cuma 14:30 ile 16:30 arasında GAP-AI projesine kod yazacağım.' },
    { label: '❓ Açıklama Gerektiren (Clarify)', text: 'Yarın koşuya çıkacağım.' },
    { label: '🚫 Desteklenmeyen (Chit-Chat)', text: 'Merhaba nasılsın, bugün bana bir fıkra anlatabilir misin?' },
  ];

  const handleSelectSample = (text: string) => {
    setInputText(text);
    setErrorMessage(null);
  };

  /**
   * Gönderim: Metni /parse uç noktasına ilet.
   */
  const handleParse = async (textToParse?: string) => {
    const text = (textToParse ?? inputText).trim();
    if (!text) {
      setErrorMessage('Lütfen planınızı açıklayan bir metin girin.');
      return;
    }

    if (!token && !mockMode) {
      setErrorMessage('API çağrısı yapabilmek için lütfen önce "Try Demo" ile oturum açın.');
      if (onRequireToken) onRequireToken();
      return;
    }

    setIsParsing(true);
    setErrorMessage(null);
    setSavedPlan(null);

    try {
      const result = await parseNaturalLanguagePlan(text, {
        language: 'tr',
        mockMode,
      });

      setParsedPlan(result);
      setIsEditing(false);

      if (result.intent === 'create_plan') {
        // Yeni bir onay oturumu için tekil UUID Idempotency-Key üret:
        setIdempotencyKey(generateIdempotencyKey());
      } else {
        setIdempotencyKey(null);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Metin çözümlenirken bir hata oluştu.';
      setErrorMessage(msg);
      setParsedPlan(null);
    } finally {
      setIsParsing(false);
    }
  };

  /**
   * Clarify akışı: Kullanıcının cevabını orijinal metinle birleştirerek tekrar /parse çağır.
   */
  const handleClarifySubmit = async () => {
    const reply = clarifyReply.trim();
    if (!reply) {
      setErrorMessage('Lütfen açıklama sorusuna bir yanıt girin.');
      return;
    }

    // Sözleşme kuralı: Orijinal girdi ile açıklama cevabını birleştir
    const combinedText = `${inputText.trim()}. ${reply}`;
    setInputText(combinedText);
    setClarifyReply('');
    await handleParse(combinedText);
  };

  /**
   * Planı onayla ve POST /plans ile kaydet.
   */
  const handleSavePlan = async () => {
    if (!parsedPlan || parsedPlan.intent !== 'create_plan') {
      setErrorMessage('Kaydedilecek geçerli bir plan bulunamadı.');
      return;
    }

    if (!idempotencyKey) {
      setErrorMessage('İstek için geçerli bir Idempotency-Key bulunamadı.');
      return;
    }

    if (!token && !mockMode) {
      setErrorMessage('Planı kaydedebilmek için lütfen oturum açın.');
      if (onRequireToken) onRequireToken();
      return;
    }

    setIsSaving(true);
    setErrorMessage(null);

    try {
      // Idempotency-Key aynı işlem denemesinde korunur:
      const planResult = await createPlan(parsedPlan, idempotencyKey, { mockMode });
      setSavedPlan(planResult);
      setParsedPlan(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Plan kaydedilirken bir hata oluştu.';
      setErrorMessage(msg);
      // Hata durumunda idempotencyKey korunur; kullanıcı tekrar "Dene" derse aynı anahtarla yineler.
    } finally {
      setIsSaving(false);
    }
  };

  /**
   * Düzenleme modunda alan güncellendiğinde idempotency anahtarını yenile.
   */
  const handleFieldChange = (field: keyof ParsedPlan, value: unknown) => {
    if (!parsedPlan) return;
    setParsedPlan({
      ...parsedPlan,
      [field]: value,
    });
    // Plan içeriği değiştiğinde mantıksal olarak yeni bir işlem oluşur:
    setIdempotencyKey(generateIdempotencyKey());
  };

  const handleResetFlow = () => {
    setInputText('');
    setClarifyReply('');
    setParsedPlan(null);
    setSavedPlan(null);
    setIdempotencyKey(null);
    setErrorMessage(null);
    setIsEditing(false);
  };

  return (
    <div className="create-plan-wrapper">
      {/* Test / Canlı Modu Göstergesi */}
      <div className="mode-toggle-bar">
        <div className="mode-toggle-left">
          <span>Mod:</span>
          <span className={`mode-badge ${mockMode ? 'mode-mock' : 'mode-live'}`} id="api-mode-badge">
            {mockMode ? '● Test / Mock Modu (B2-2 Bağımsız)' : '● Canlı Backend API'}
          </span>
        </div>
        <button
          type="button"
          className="mode-toggle-btn"
          id="toggle-mock-mode-btn"
          onClick={() => {
            const nextMode = !mockMode;
            setMockMode(nextMode);
            setErrorMessage(null);
          }}
        >
          {mockMode ? 'Canlı API Moduna Geç' : 'Mock Moduna Geç'}
        </button>
      </div>

      {/* Hata Bildirimi */}
      {errorMessage && (
        <div className="alert alert-error" role="alert" id="plan-error-alert">
          <span className="alert-icon">⚠️</span>
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Desteklenmeyen (Unsupported) Uyarı Bildirimi */}
      {parsedPlan && parsedPlan.intent === 'unsupported' && (
        <div className="alert alert-error" role="alert" id="unsupported-alert">
          <span className="alert-icon">🚫</span>
          <span>
            <strong>Plan Algılanamadı (Unsupported):</strong> Girdiğiniz metin bir hedef, aktivite veya eylem planı olarak yorumlanamadı. Sistem desteklenmeyen bu girdiyi plana dönüştürmez ve kaydetmeye izin vermez.
          </span>
        </div>
      )}

      {/* Adım 1: Metin Giriş Kartı */}
      {!savedPlan && (
        <section className="card plan-input-card">
          <div className="card-header">
            <h2>Doğal Dilde Planınızı Yazın</h2>
            <span className="badge">POST /parse</span>
          </div>

          <p className="card-desc">
            Hedefinizi, gününü ve saatini doğal bir dille yazın. GAP-AI yapay zekâsı ifadenizi
            ayrıştıracak ve onayınıza sunacaktır.
          </p>

          <div className="samples-row">
            <span className="samples-label">Örnekler:</span>
            {SAMPLE_PROMPTS.map((sample, idx) => (
              <button
                key={idx}
                type="button"
                className="sample-chip"
                onClick={() => handleSelectSample(sample.text)}
                disabled={isParsing || isSaving}
              >
                {sample.label}
              </button>
            ))}
          </div>

          <div className="textarea-container">
            <textarea
              id="plan-input-textarea"
              className="plan-textarea"
              placeholder="Örnek: Yarın saat 18:00'de Belgrad Ormanı'nda 1 saat tempolu koşu yapacağım."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={isParsing || isSaving}
              rows={3}
            />
            <div className="textarea-footer">
              <span>{inputText.length} karakter</span>
              <span>D-004 tek AI şeması (ai/schema.json)</span>
            </div>
          </div>

          <div className="action-row">
            <button
              id="submit-parse-btn"
              type="button"
              className="btn btn-primary"
              onClick={() => handleParse()}
              disabled={isParsing || isSaving || !inputText.trim()}
            >
              {isParsing ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Ayrıştırılıyor...</span>
                </>
              ) : (
                'Planı Ayrıştır'
              )}
            </button>

            {(parsedPlan || inputText) && (
              <button
                id="reset-plan-btn"
                type="button"
                className="btn btn-secondary"
                onClick={handleResetFlow}
                disabled={isParsing || isSaving}
              >
                Temizle
              </button>
            )}
          </div>
        </section>
      )}

      {/* Adım 2A: Clarify Kartı (Soru ve Yanıt Girişi) */}
      {parsedPlan && parsedPlan.intent === 'clarify' && (
        <section className="card clarify-card" id="clarify-card">
          <div className="clarify-header">
            <span className="clarify-icon">💬</span>
            <h3 className="clarify-title">Ek Bilgi Gerekiyor (Clarify)</h3>
          </div>

          <p className="card-desc">
            Model planınızı tespit etti ancak belirli zorunlu alanlar eksik veya belirsiz olduğu
            için tahmin yürütmek yerine size bir açıklama sorusu yöneltti:
          </p>

          <div className="clarify-question-box" id="clarification-question-text">
            "{parsedPlan.clarification_question}"
          </div>

          <div className="textarea-container">
            <input
              type="text"
              id="clarify-reply-input"
              className="clarify-reply-input"
              placeholder="Yanıtınızı yazın (Örnek: Saat 18:30'da)"
              value={clarifyReply}
              onChange={(e) => setClarifyReply(e.target.value)}
              disabled={isParsing}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleClarifySubmit();
                }
              }}
            />
          </div>

          <div className="action-row">
            <button
              id="submit-clarify-btn"
              type="button"
              className="btn btn-primary"
              onClick={handleClarifySubmit}
              disabled={isParsing || !clarifyReply.trim()}
            >
              {isParsing ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Gönderiliyor...</span>
                </>
              ) : (
                'Cevapla ve Tekrar Ayrıştır'
              )}
            </button>
          </div>
        </section>
      )}

      {/* Adım 2B: Unsupported Kartı (Desteklenmeyen İstek Uyarısı) */}
      {parsedPlan && parsedPlan.intent === 'unsupported' && (
        <section className="card unsupported-card" id="unsupported-card">
          <div className="unsupported-header">
            <span className="alert-icon">🚫</span>
            <h3 className="unsupported-title">Plan Algılanamadı (Unsupported)</h3>
          </div>
          <div className="unsupported-body">
            Girdiğiniz metin bir hedef, aktivite veya eylem planı olarak yorumlanamadı. Sistem
            desteklenmeyen bu girdiyi plana dönüştürmez ve veritabanına kaydetmez. Lütfen yapmak
            istediğiniz eylemi belirterek tekrar deneyin.
          </div>
          <div className="action-row">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setInputText('');
                setParsedPlan(null);
              }}
            >
              Farklı Bir Metin Yaz
            </button>
          </div>
        </section>
      )}

      {/* Adım 2C: Onay Kartı (create_plan Sonucu & POST /plans) */}
      {parsedPlan && parsedPlan.intent === 'create_plan' && (
        <section className="card confirmation-card" id="plan-confirmation-card">
          <div className="card-header">
            <h2>Plan Onay Ekranı</h2>
            <span className="status-pill pill-active">Hazır</span>
          </div>

          <p className="card-desc">
            Ayrıştırılan plan detaylarını inceleyin. Bilgileri onayladığınızda planınız backend'e
            kaydedilecektir.
          </p>

          {!isEditing ? (
            <div className="parsed-fields-grid" id="parsed-fields-view">
              <div className="parsed-field-item">
                <span className="parsed-field-label">Başlık</span>
                <span className="parsed-field-value" id="field-title">{parsedPlan.title}</span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Kategori</span>
                <span className={`category-tag category-${parsedPlan.category || 'other'}`} id="field-category">
                  {parsedPlan.category || 'Belirtilmedi'}
                </span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Tarih</span>
                <span className="parsed-field-value" id="field-date">{parsedPlan.date}</span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Saat</span>
                <span className="parsed-field-value" id="field-time">{parsedPlan.time}</span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Süre</span>
                <span className="parsed-field-value" id="field-duration">
                  {parsedPlan.duration_minutes ? `${parsedPlan.duration_minutes} dk` : '60 dk (Varsayılan)'}
                </span>
              </div>

              <div className="parsed-field-item">
                <span className="parsed-field-label">Hava Durumu Kontrolü</span>
                <span className="parsed-field-value" id="field-weather">
                  {parsedPlan.needs_weather_check ? 'Açık (Açık Alan)' : 'Kapalı (Kapalı Alan)'}
                </span>
              </div>
            </div>
          ) : (
            <div className="edit-form-grid" id="parsed-fields-edit-grid">
              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-title">Başlık</label>
                <input
                  id="edit-title"
                  type="text"
                  className="edit-input"
                  value={parsedPlan.title || ''}
                  onChange={(e) => handleFieldChange('title', e.target.value)}
                />
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-category">Kategori</label>
                <select
                  id="edit-category"
                  className="edit-input"
                  value={parsedPlan.category || 'other'}
                  onChange={(e) => handleFieldChange('category', e.target.value as PlanCategory)}
                >
                  <option value="sport">Sport</option>
                  <option value="study">Study</option>
                  <option value="work">Work</option>
                  <option value="meeting">Meeting</option>
                  <option value="health">Health</option>
                  <option value="social">Social</option>
                  <option value="personal">Personal</option>
                  <option value="other">Other</option>
                </select>
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-date">Tarih</label>
                <input
                  id="edit-date"
                  type="date"
                  className="edit-input"
                  value={parsedPlan.date || ''}
                  onChange={(e) => handleFieldChange('date', e.target.value)}
                />
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-time">Saat</label>
                <input
                  id="edit-time"
                  type="time"
                  className="edit-input"
                  value={parsedPlan.time || ''}
                  onChange={(e) => handleFieldChange('time', e.target.value)}
                />
              </div>

              <div className="parsed-field-item">
                <label className="parsed-field-label" htmlFor="edit-duration">Süre (dakika)</label>
                <input
                  id="edit-duration"
                  type="number"
                  min={5}
                  max={1440}
                  className="edit-input"
                  value={parsedPlan.duration_minutes ?? 60}
                  onChange={(e) =>
                    handleFieldChange(
                      'duration_minutes',
                      e.target.value ? parseInt(e.target.value, 10) : null
                    )
                  }
                />
              </div>
            </div>
          )}

          {/* Idempotency Key Bilgi Çubuğu */}
          <div className="idempotency-box">
            <span>Idempotency-Key (UUID v4):</span>
            <code className="idempotency-key-code" id="active-idempotency-key">
              {idempotencyKey}
            </code>
          </div>

          <div className="action-row">
            <button
              id="confirm-save-plan-btn"
              type="button"
              className="btn btn-success"
              onClick={handleSavePlan}
              disabled={isSaving || !idempotencyKey}
            >
              {isSaving ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Kaydediliyor...</span>
                </>
              ) : (
                '✓ Planı Onayla ve Kaydet'
              )}
            </button>

            <button
              id="toggle-edit-mode-btn"
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsEditing(!isEditing)}
              disabled={isSaving}
            >
              {isEditing ? 'Düzenlemeyi Bitir' : 'Alanları Düzenle'}
            </button>

            <button
              id="cancel-plan-btn"
              type="button"
              className="btn btn-secondary"
              onClick={() => setParsedPlan(null)}
              disabled={isSaving}
            >
              Vazgeç
            </button>
          </div>
        </section>
      )}

      {/* Adım 3: Kayıt Başarı Kartı */}
      {savedPlan && (
        <section className="card saved-success-card" id="plan-saved-card">
          <div className="success-header">
            <span className="success-icon">🎉</span>
            <h2 className="success-title">Plan Başarıyla Kaydedildi!</h2>
          </div>

          <p className="card-desc">
            Planınız veritabanına başarıyla eklendi. Hatırlatıcılar ve hava durumu analizleri bu plan
            üzerinden takip edilecektir.
          </p>

          <div className="plan-details-table">
            <div className="plan-detail-row">
              <span className="label">Plan ID:</span>
              <span className="val" id="saved-plan-id"><code>{savedPlan.id}</code></span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Başlık:</span>
              <span className="val" id="saved-plan-title">{savedPlan.title}</span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Başlangıç Zamanı:</span>
              <span className="val" id="saved-plan-start">{new Date(savedPlan.planned_start).toLocaleString('tr-TR')}</span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Bitiş Zamanı:</span>
              <span className="val" id="saved-plan-end">{new Date(savedPlan.planned_end).toLocaleString('tr-TR')}</span>
            </div>
            <div className="plan-detail-row">
              <span className="label">Kayıt Kaynağı:</span>
              <span className="val" id="saved-plan-source">{savedPlan.source}</span>
            </div>
          </div>

          <div className="action-row">
            <button
              id="create-another-plan-btn"
              type="button"
              className="btn btn-primary"
              onClick={handleResetFlow}
            >
              + Yeni Bir Plan Oluştur
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
