import React from 'react';
import { AlertTriangle, KeyRound, RotateCcw } from 'lucide-react';
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
  onRequireAuth?: () => void;
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
  onRequireAuth,
}) => {
  const isTimeout =
    errorType === 'timeout_error' ||
    statusCode === 408 ||
    message.toLowerCase().includes('timed out') ||
    message.toLowerCase().includes('timeout');

  const isAborted = errorType === 'aborted';

  const isNetworkOrDown =
    !isTimeout &&
    !isAborted &&
    (errorType === 'network_error' ||
      statusCode === 0 ||
      message.toLowerCase().includes('connect') ||
      message.toLowerCase().includes('network') ||
      message.toLowerCase().includes('offline'));

  const resolvedTitle =
    title ||
    (statusCode === 401 || errorType === 'auth_required'
      ? 'Session Required'
      : isTimeout
      ? 'Request Timed Out'
      : isAborted
      ? 'Request Cancelled'
      : isNetworkOrDown
      ? 'Backend Service Offline'
      : statusCode
      ? `Request Failed (${statusCode})`
      : 'Unable to Load Data');

  const requiresAuth = statusCode === 401 || errorType === 'auth_required';
  const resolvedHint = requiresAuth
    ? 'Your session is missing or expired. Start a new demo session or provide a valid access token to continue.'
    : isTimeout
      ? 'The server took longer than expected to respond. Please try again.'
      : isAborted
        ? 'The request was cancelled before it could complete.'
        : isNetworkOrDown
          ? 'Unable to reach the GAP-AI service. Check your internet connection and try again.'
          : 'If this issue persists, refresh the page or contact your administrator.';

  return (
    <section className="error-state-card" id={id} role="alert" aria-live="assertive">
      <div className="error-state-icon-wrapper" aria-hidden="true">
        <AlertTriangle size={26} strokeWidth={1.8} />
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

      {requiresAuth && onRequireAuth ? (
        <div className="error-state-actions">
          <button
            id={`${id}-auth-btn`}
            type="button"
            className="btn btn-primary error-state-retry-btn"
            onClick={onRequireAuth}
          >
            <KeyRound size={17} aria-hidden="true" />
            <span>Open Demo &amp; Auth</span>
          </button>
        </div>
      ) : onRetry ? (
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
                <RotateCcw size={17} aria-hidden="true" />
                <span>{retryText}</span>
              </>
            )}
          </button>
        </div>
      ) : null}
    </section>
  );
};

export default ErrorState;
