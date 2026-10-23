import React from 'react';
import { CalendarClock } from 'lucide-react';
import type { PostponedTarget } from '../../api/insights';

export interface PostponedTargetsListProps {
  targets?: PostponedTarget[];
}

export const PostponedTargetsList: React.FC<PostponedTargetsListProps> = ({
  targets = [],
}) => {
  return (
    <section className="chart-card postponed-targets-card" id="postponed-targets-section">
      <div className="chart-header">
        <div>
          <span className="chart-eyebrow">Postponement Patterns</span>
          <h3 className="chart-title">Postponed Target Slots</h3>
        </div>
        <span className="targets-count-badge">
          {targets.length} {targets.length === 1 ? 'Slot' : 'Slots'}
        </span>
      </div>

      <p className="section-desc">
        Most frequent days and hours chosen when postponing plans:
      </p>

      {targets.length === 0 ? (
        <div className="no-postponed-data" id="empty-postponed-targets">
          <CalendarClock className="no-data-icon" aria-hidden="true" />
          <span>No postponed target slots recorded in this period.</span>
        </div>
      ) : (
        <div className="targets-grid" id="postponed-targets-grid">
          {targets.map((target, idx) => {
            const hourFormatted = `${String(target.hour).padStart(2, '0')}:00`;

            return (
              <div
                key={`${target.weekday}-${target.hour}-${idx}`}
                className="target-item"
                id={`postponed-target-${idx}`}
              >
                <div className="target-time">
                  <span className="target-weekday">{target.weekday}</span>
                  <span className="target-hour">{hourFormatted}</span>
                </div>
                <div
                  className="target-count-pill"
                  title={`Postponed to this slot ${target.count} times`}
                >
                  <span className="target-count-val">{target.count}</span>
                  <span className="target-count-label">postponed</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default PostponedTargetsList;
