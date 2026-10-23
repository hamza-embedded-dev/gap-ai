import React from 'react';

export interface SampleDataBadgeProps {
  className?: string;
}

export const SampleDataBadge: React.FC<SampleDataBadgeProps> = ({ className = '' }) => {
  return (
    <span
      id="sample-data-badge"
      className={`sample-data-badge ${className}`}
      title="This analysis was calculated using synthetic data from a demo session."
    >
      <span className="badge-dot" aria-hidden="true"></span>
      Sample Data
    </span>
  );
};

export default SampleDataBadge;
