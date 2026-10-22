import React from 'react';
import './Skeleton.css';

export interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
  variant?: 'text' | 'rectangular' | 'circular';
  style?: React.CSSProperties;
  ariaLabel?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  className = '',
  width,
  height,
  variant = 'rectangular',
  style = {},
  ariaLabel = 'Loading content...',
}) => {
  const variantClass =
    variant === 'circular'
      ? 'skeleton-circle'
      : variant === 'text'
      ? 'skeleton-text'
      : '';

  const inlineStyles: React.CSSProperties = {
    ...style,
    ...(width !== undefined ? { width } : {}),
    ...(height !== undefined ? { height } : {}),
  };

  return (
    <div
      className={`skeleton ${variantClass} ${className}`.trim()}
      style={inlineStyles}
      role="status"
      aria-label={ariaLabel}
      aria-busy="true"
    />
  );
};

export default Skeleton;
