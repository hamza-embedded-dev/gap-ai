import React from 'react';
import type { WeekdayStats, HourStats } from '../../api/insights';

export interface DistributionChartsProps {
  byWeekday?: Record<string, WeekdayStats>;
  byHour?: Record<string, HourStats>;
}

const WEEKDAYS_ORDER = [
  { key: 'Monday', label: 'Mon', full: 'Monday' },
  { key: 'Tuesday', label: 'Tue', full: 'Tuesday' },
  { key: 'Wednesday', label: 'Wed', full: 'Wednesday' },
  { key: 'Thursday', label: 'Thu', full: 'Thursday' },
  { key: 'Friday', label: 'Fri', full: 'Friday' },
  { key: 'Saturday', label: 'Sat', full: 'Saturday' },
  { key: 'Sunday', label: 'Sun', full: 'Sunday' },
];

export const DistributionCharts: React.FC<DistributionChartsProps> = ({
  byWeekday = {},
  byHour = {},
}) => {
  // Prepare weekday data:
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

  // Prepare hourly data (API contract: {"18": {"planned": 3, "done": 2}})
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
      {/* Weekday Distribution Card */}
      <section className="chart-card" id="weekday-distribution-card">
        <div className="chart-header">
          <div>
            <span className="chart-eyebrow">Weekly Distribution</span>
            <h3 className="chart-title">Planned vs. Completed by Weekday</h3>
          </div>
          <div className="chart-legend">
            <span className="legend-item">
              <span className="legend-dot dot-planned" aria-hidden="true"></span>
              Planned
            </span>
            <span className="legend-item">
              <span className="legend-dot dot-done" aria-hidden="true"></span>
              Completed
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
                  {/* Planned Bar */}
                  <div
                    className="bar bar-planned"
                    style={{ width: `${Math.max(day.planned > 0 ? 6 : 0, plannedWidth)}%` }}
                    title={`${day.full} - Planned: ${day.planned}`}
                  >
                    {day.planned > 0 && <span className="bar-num">{day.planned}</span>}
                  </div>
                  {/* Completed Bar */}
                  <div
                    className="bar bar-done"
                    style={{ width: `${Math.max(day.done > 0 ? 6 : 0, doneWidth)}%` }}
                    title={`${day.full} - Completed: ${day.done}`}
                  >
                    {day.done > 0 && <span className="bar-num">{day.done}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Hour Distribution Card */}
      <section className="chart-card" id="hour-distribution-card">
        <div className="chart-header">
          <div>
            <span className="chart-eyebrow">Time Distribution</span>
            <h3 className="chart-title">Distribution by Hour of Day</h3>
          </div>
          <div className="chart-legend">
            <span className="legend-item">
              <span className="legend-dot dot-planned" aria-hidden="true"></span>
              Planned
            </span>
            <span className="legend-item">
              <span className="legend-dot dot-done" aria-hidden="true"></span>
              Completed
            </span>
          </div>
        </div>

        {hourEntries.length === 0 ? (
          <div className="no-chart-data">No hourly activity recorded for this period.</div>
        ) : (
          <div className="chart-bars-vertical" tabIndex={0} role="region" aria-label="Hourly activity chart">
            {hourEntries.map((item) => {
              const plannedHeight = (item.planned / maxHourVal) * 100;
              const doneHeight = (item.done / maxHourVal) * 100;

              return (
                <div key={item.hour} className="hour-col" id={`hour-col-${item.hour}`}>
                  <div className="col-track">
                    <div
                      className="col-bar bar-planned"
                      style={{ height: `${Math.max(item.planned > 0 ? 8 : 0, plannedHeight)}%` }}
                      title={`${item.label} - Planned: ${item.planned}`}
                    >
                      {item.planned > 0 && <span className="col-num">{item.planned}</span>}
                    </div>
                    <div
                      className="col-bar bar-done"
                      style={{ height: `${Math.max(item.done > 0 ? 8 : 0, doneHeight)}%` }}
                      title={`${item.label} - Completed: ${item.done}`}
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

export default DistributionCharts;
