import React from 'react';
import './ErrorState.css';

export interface ErrorStateProps {
  id?: string;
  title?: string;
  message?: string;
  statusCode?: number;
  errorType?: string;
  onRetry?: () => void;
  isRetrying?: boolean;
  retryText?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  id = 'error-state-card',
  title,
  message = 'An unexpected error occurred while communicating with the service.',
  statusCode,
  errorType,
  onRetry,
  isRetrying = false,
  retryText = 'Retry Connection',
}) => {
  const isNetworkOrDown =
    errorType === 'network_error' ||
    statusCode === 0 ||
    message.toLowerCase().includes('connect') ||
    message.toLowerCase().includes('network') ||
    message.toLowerCase().includes('offline');

  const resolvedTitle =
    title ||
    (isNetworkOrDown
      ? 'Backend Service Offline'
      : statusCode
      ? `Request Failed (${statusCode})`
      : 'Unable to Load Data');

  const resolvedHint = isNetworkOrDown
    ? 'Unable to reach the GAP-AI backend. Please check your internet connection or ensure the local backend service is running on the expected port.'
    : 'If this issue persists, please refresh the page or verify your session authorization.';

  return (
    <section className="error-state-card" id={id} role="alert" aria-live="assertive">
      <div className="error-state-icon-wrapper" aria-hidden="true">
        <span>⚠️</span>
      </div>

      {statusCode !== undefined && statusCode > 0 && (
        <span className="error-state-badge" id={`${id}-status-badge`}>
          HTTP {statusCode}
        </span>
      )}

      <h3 className="error-state-title" id={`${id}-title`}>
        {resolvedTitle}
      </h3>

      <p className="error-state-message" id={`${id}-message`}>
        {message}
      </p>

      <div className="error-state-hint" id={`${id}-hint`}>
        {resolvedHint}
      </div>

      {onRetry && (
        <div className="error-state-actions">
          <button
            id={`${id}-retry-btn`}
            type="button"
            className="btn btn-primary error-state-retry-btn"
            onClick={onRetry}
            disabled={isRetrying}
          >
            {isRetrying ? (
              <>
                <span className="spinner" aria-hidden="true"></span>
                <span>Retrying...</span>
              </>
            ) : (
              <>
                <span aria-hidden="true">↻</span>
                <span>{retryText}</span>
              </>
            )}
          </button>
        </div>
      )}
    </section>
  );
};

export default ErrorState;
