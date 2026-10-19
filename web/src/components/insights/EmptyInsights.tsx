import React from 'react';

interface EmptyInsightsProps {
  periodLabel?: string;
  onRefresh?: () => void;
}

export const EmptyInsights: React.FC<EmptyInsightsProps> = ({
  periodLabel = 'seçili periyot',
  onRefresh,
}) => {
  return (
    <div className="empty-insights-card" id="empty-insights-state">
      <div className="empty-insights-icon" aria-hidden="true">
        📊
      </div>
      <h3 className="empty-insights-title">Not enough data</h3>
      <p className="empty-insights-desc">
        {periodLabel} için analiz hesaplamaya yetecek tamamlanmış veya sonucu bildirilmiş plan bulunamadı.
      </p>
      <div className="empty-insights-hint">
        Planlarınıza sadakat ve davranış analizlerini görebilmek için plan ekleyin veya sonuçlarını (tamamlandı, ertelendi) bildirin.
      </div>
      {onRefresh && (
        <button
          type="button"
          className="btn btn-secondary empty-refresh-btn"
          onClick={onRefresh}
        >
          Yeniden Kontrol Et
        </button>
      )}
    </div>
  );
};
