import React from 'react';
import type { PostponedTarget } from '../../api/insights';

interface PostponedTargetsListProps {
  targets?: PostponedTarget[];
}

const WEEKDAY_TR: Record<string, string> = {
  Monday: 'Pazartesi',
  Tuesday: 'Salı',
  Wednesday: 'Çarşamba',
  Thursday: 'Perşembe',
  Friday: 'Cuma',
  Saturday: 'Cumartesi',
  Sunday: 'Pazar',
};

export const PostponedTargetsList: React.FC<PostponedTargetsListProps> = ({
  targets = [],
}) => {
  return (
    <section className="chart-card postponed-targets-card" id="postponed-targets-section">
      <div className="chart-header">
        <div>
          <span className="chart-eyebrow">Erteleme Örüntüleri</span>
          <h3 className="chart-title">Ertelenen Hedef Zamanlar</h3>
        </div>
        <span className="targets-count-badge">
          {targets.length} {targets.length === 1 ? 'Örüntü' : 'Örüntü'}
        </span>
      </div>

      <p className="section-desc">
        Planlarınızı ertelediğinizde en çok tercih ettiğiniz hedef gün ve saat dilimleri:
      </p>

      {targets.length === 0 ? (
        <div className="no-postponed-data" id="empty-postponed-targets">
          <span className="no-data-icon" aria-hidden="true">
            🎯
          </span>
          <span>Bu periyotta kaydedilmiş bir erteleme hedefi bulunmuyor.</span>
        </div>
      ) : (
        <div className="targets-grid" id="postponed-targets-grid">
          {targets.map((target, idx) => {
            const dayName = WEEKDAY_TR[target.weekday] || target.weekday;
            const hourFormatted = `${String(target.hour).padStart(2, '0')}:00`;

            return (
              <div
                key={`${target.weekday}-${target.hour}-${idx}`}
                className="target-item"
                id={`postponed-target-${idx}`}
              >
                <div className="target-time">
                  <span className="target-weekday">{dayName}</span>
                  <span className="target-hour">{hourFormatted}</span>
                </div>
                <div className="target-count-pill" title={`${target.count} kez bu zamana ertelendi`}>
                  <span className="target-count-val">{target.count}</span>
                  <span className="target-count-label">erteleme</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};
