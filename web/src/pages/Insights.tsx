import React, { useCallback, useEffect, useState } from 'react';
import { fetchInsights } from '../api/insights';
import type { InsightsPeriod, InsightsResponse } from '../api/insights';
import { AdherenceMetricCard } from '../components/insights/AdherenceMetricCard';
import { DistributionCharts } from '../components/insights/DistributionCharts';
import { PostponedTargetsList } from '../components/insights/PostponedTargetsList';
import { EmptyInsights } from '../components/insights/EmptyInsights';
import { SampleDataBadge } from '../components/insights/SampleDataBadge';
import './Insights.css';

const PERIOD_LABELS: Record<InsightsPeriod, string> = {
  week: 'Bu Hafta (Week)',
  last_week: 'Geçen Hafta (Last Week)',
  all: 'Tüm Zamanlar (All)',
};

export const Insights: React.FC = () => {
  const [period, setPeriod] = useState<InsightsPeriod>('week');
  const [insights, setInsights] = useState<InsightsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadData = useCallback(async (selectedPeriod: InsightsPeriod) => {
    setIsLoading(true);
    setErrorMessage(null);

    try {
      const data = await fetchInsights(selectedPeriod);
      setInsights(data);
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : 'Analiz verileri alınırken beklenmeyen bir hata oluştu.';
      setErrorMessage(msg);
      setInsights(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let isCancelled = false;

    const run = async () => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const data = await fetchInsights(period);
        if (!isCancelled) {
          setInsights(data);
        }
      } catch (err) {
        if (!isCancelled) {
          const msg =
            err instanceof Error
              ? err.message
              : 'Analiz verileri alınırken beklenmeyen bir hata oluştu.';
          setErrorMessage(msg);
          setInsights(null);
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    };

    void run();

    return () => {
      isCancelled = true;
    };
  }, [period]);

  const handlePeriodChange = (newPeriod: InsightsPeriod) => {
    if (newPeriod !== period) {
      setPeriod(newPeriod);
    }
  };

  const isDemo =
    insights?.data_label === 'demo' ||
    insights?.is_demo === true;

  // Veri boş mu veya yeterli veri yok mu kontrolü:
  // API sözleşmesine göre uygun plan yoksa adherence_pct değeri null döner veya planned 0'dır.
  const hasEnoughData =
    insights !== null &&
    insights.planned > 0 &&
    insights.adherence_pct !== null &&
    insights.adherence_pct !== undefined;

  return (
    <div className="insights-page" id="insights-dashboard">
      {/* Üst Başlık ve Filtreleme Çubuğu */}
      <header className="insights-top-bar">
        <div className="insights-heading-group">
          <div className="insights-title-row">
            <h1 className="insights-main-title">Davranış &amp; Uyum Analizi</h1>
            {isDemo && <SampleDataBadge />}
          </div>
          <p className="insights-subtitle">
            Planlarınıza uyum durumunuzu, erteleme alışkanlıklarınızı ve zaman dağılımınızı izleyin.
          </p>
        </div>

        {/* Periyot Seçici */}
        <div
          className="period-selector-wrapper"
          role="group"
          aria-label="Analiz Periyodu Seçimi"
          id="period-selector"
        >
          {(['week', 'last_week', 'all'] as InsightsPeriod[]).map((p) => (
            <button
              key={p}
              id={`period-btn-${p}`}
              type="button"
              className={`period-btn ${period === p ? 'active' : ''}`}
              onClick={() => handlePeriodChange(p)}
              disabled={isLoading}
              aria-pressed={period === p}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </header>

      {/* Yükleniyor Durumu */}
      {isLoading && (
        <div className="insights-loading-box" id="insights-loading" role="status">
          <div className="insights-spinner" aria-hidden="true"></div>
          <span className="loading-text">Analiz verileri yükleniyor ({PERIOD_LABELS[period]})...</span>
        </div>
      )}

      {/* Hata Durumu */}
      {!isLoading && errorMessage && (
        <div className="insights-error-box" id="insights-error" role="alert">
          <h3 className="error-title">Veri Alınamadı</h3>
          <p className="error-message">{errorMessage}</p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => loadData(period)}
          >
            Tekrar Dene
          </button>
        </div>
      )}

      {/* Veri Yok ("Not enough data") Durumu */}
      {!isLoading && !errorMessage && !hasEnoughData && (
        <EmptyInsights
          periodLabel={PERIOD_LABELS[period]}
          onRefresh={() => loadData(period)}
        />
      )}

      {/* Gerçek Veri Görselleştirme Durumu */}
      {!isLoading && !errorMessage && hasEnoughData && insights && (
        <>
          {/* Uyum Yüzdesi & Özet Sayaçlar */}
          <AdherenceMetricCard insights={insights} />

          {/* Gün ve Saat Dağılım Grafikleri */}
          <DistributionCharts
            byWeekday={insights.by_weekday}
            byHour={insights.by_hour}
          />

          {/* Ertelenen Hedefler */}
          <PostponedTargetsList targets={insights.postponed_targets} />
        </>
      )}
    </div>
  );
};

export default Insights;
