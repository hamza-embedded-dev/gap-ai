import React from 'react';
import type { WeekdayStats, HourStats } from '../../api/insights';

interface DistributionChartsProps {
  byWeekday?: Record<string, WeekdayStats>;
  byHour?: Record<string, HourStats>;
}

const WEEKDAYS_ORDER = [
  { key: 'Monday', label: 'Pzt', full: 'Pazartesi' },
  { key: 'Tuesday', label: 'Sal', full: 'Salı' },
  { key: 'Wednesday', label: 'Çar', full: 'Çarşamba' },
  { key: 'Thursday', label: 'Per', full: 'Perşembe' },
  { key: 'Friday', label: 'Cum', full: 'Cuma' },
  { key: 'Saturday', label: 'Cmt', full: 'Cumartesi' },
  { key: 'Sunday', label: 'Paz', full: 'Pazar' },
];

export const DistributionCharts: React.FC<DistributionChartsProps> = ({
  byWeekday = {},
  byHour = {},
}) => {
  // Haftalık gün verilerini hazırla:
  const weekdayData = WEEKDAYS_ORDER.map(({ key, label, full }) => {
    const stats = byWeekday[key] || byWeekday[full] || { planned: 0, done: 0, postponed: 0 };
    return {
      key,
      label,
      full,
      planned: stats.planned || 0,
      done: stats.done || 0,
      postponed: stats.postponed || 0,
    };
  });

  const maxWeekdayVal = Math.max(
    1,
    ...weekdayData.map((d) => Math.max(d.planned, d.done + d.postponed))
  );

  // Saatlik verileri hazırla:
  // by_hour sözleşmede {"18": {"planned": 3, "done": 2}} şeklinde
  const hourEntries = Object.entries(byHour)
    .map(([hourStr, stats]) => ({
      hour: parseInt(hourStr, 10),
      label: `${hourStr.padStart(2, '0')}:00`,
      planned: stats.planned || 0,
      done: stats.done || 0,
      postponed: stats.postponed || 0,
    }))
    .sort((a, b) => a.hour - b.hour);

  const maxHourVal = Math.max(
    1,
    ...hourEntries.map((d) => Math.max(d.planned, d.done))
  );

  return (
    <div className="distribution-charts-container" id="distribution-charts">
      {/* Gün Dağılımı Kartı */}
      <section className="chart-card" id="weekday-distribution-card">
        <div className="chart-header">
          <div>
            <span className="chart-eyebrow">Haftalık Dağılım</span>
            <h3 className="chart-title">Günlere Göre Plan ve Gerçekleşme</h3>
          </div>
          <div className="chart-legend">
            <span className="legend-item">
              <span className="legend-dot dot-planned" aria-hidden="true"></span>
              Planlanan
            </span>
            <span className="legend-item">
              <span className="legend-dot dot-done" aria-hidden="true"></span>
              Tamamlanan
            </span>
          </div>
        </div>

        <div className="chart-bars-horizontal">
          {weekdayData.map((day) => {
            const plannedWidth = (day.planned / maxWeekdayVal) * 100;
            const doneWidth = (day.done / maxWeekdayVal) * 100;

            return (
              <div key={day.key} className="weekday-row" id={`weekday-row-${day.key.toLowerCase()}`}>
                <div className="row-label" title={day.full}>
                  {day.label}
                </div>
                <div className="row-track">
                  {/* Planlanan Çubuğu */}
                  <div
                    className="bar bar-planned"
                    style={{ width: `${Math.max(day.planned > 0 ? 6 : 0, plannedWidth)}%` }}
                    title={`${day.full} - Planlanan: ${day.planned}`}
                  >
                    {day.planned > 0 && <span className="bar-num">{day.planned}</span>}
                  </div>
                  {/* Tamamlanan Çubuğu */}
                  <div
                    className="bar bar-done"
                    style={{ width: `${Math.max(day.done > 0 ? 6 : 0, doneWidth)}%` }}
                    title={`${day.full} - Tamamlanan: ${day.done}`}
                  >
                    {day.done > 0 && <span className="bar-num">{day.done}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Saat Dağılımı Kartı */}
      <section className="chart-card" id="hour-distribution-card">
        <div className="chart-header">
          <div>
            <span className="chart-eyebrow">Zaman Dilimi</span>
            <h3 className="chart-title">Günün Saatlerine Göre Dağılım</h3>
          </div>
          <div className="chart-legend">
            <span className="legend-item">
              <span className="legend-dot dot-planned" aria-hidden="true"></span>
              Planlanan
            </span>
            <span className="legend-item">
              <span className="legend-dot dot-done" aria-hidden="true"></span>
              Tamamlanan
            </span>
          </div>
        </div>

        {hourEntries.length === 0 ? (
          <div className="no-chart-data">Bu periyotta saatlik aktivite kaydı yok.</div>
        ) : (
          <div className="chart-bars-vertical">
            {hourEntries.map((item) => {
              const plannedHeight = (item.planned / maxHourVal) * 100;
              const doneHeight = (item.done / maxHourVal) * 100;

              return (
                <div key={item.hour} className="hour-col" id={`hour-col-${item.hour}`}>
                  <div className="col-track">
                    <div
                      className="col-bar bar-planned"
                      style={{ height: `${Math.max(item.planned > 0 ? 8 : 0, plannedHeight)}%` }}
                      title={`${item.label} - Planlanan: ${item.planned}`}
                    >
                      {item.planned > 0 && <span className="col-num">{item.planned}</span>}
                    </div>
                    <div
                      className="col-bar bar-done"
                      style={{ height: `${Math.max(item.done > 0 ? 8 : 0, doneHeight)}%` }}
                      title={`${item.label} - Tamamlanan: ${item.done}`}
                    >
                      {item.done > 0 && <span className="col-num">{item.done}</span>}
                    </div>
                  </div>
                  <div className="col-label">{item.hour}</div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
};
