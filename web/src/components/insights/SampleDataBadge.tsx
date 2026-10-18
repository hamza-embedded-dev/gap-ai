import React from 'react';

interface SampleDataBadgeProps {
  className?: string;
}

export const SampleDataBadge: React.FC<SampleDataBadgeProps> = ({ className = '' }) => {
  return (
    <span
      id="sample-data-badge"
      className={`sample-data-badge ${className}`}
      title="Bu analiz demo oturumuna ait sentetik verilerle hesaplanmıştır."
    >
      <span className="badge-dot" aria-hidden="true"></span>
      Sample Data
    </span>
  );
};
