import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError, apiFetch } from '../src/api/client.ts';
import { ErrorState } from '../src/components/ui/ErrorState.tsx';
import { CoachView } from '../src/components/coach/CoachView.tsx';
import { fetchInsights } from '../src/api/insights.ts';

describe('Personal AI Coach Timeout and Offline False-Positive Regression Tests', () => {
  describe('1. apiFetch Abort and Timeout Differentiation', () => {
    it('translates DOMException TimeoutError into ApiError timeout_error (HTTP 408)', async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async () => {
        const error = new DOMException('The operation timed out.', 'TimeoutError');
        throw error;
      };

      try {
        await apiFetch('/insights');
        assert.fail('apiFetch should have thrown');
      } catch (err) {
        assert.ok(err instanceof ApiError, 'Expected ApiError');
        assert.equal(err.status, 408);
        assert.equal(err.errorType, 'timeout_error');
        assert.ok(
          err.message.includes('Request timed out'),
          `Message should mention timeout, got: ${err.message}`
        );
        assert.ok(
          !err.message.includes('Please ensure the backend service is running'),
          'Timeout should not claim backend is offline'
        );
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('translates AbortError with timeout reason into ApiError timeout_error (HTTP 408)', async () => {
      const originalFetch = globalThis.fetch;
      const controller = new AbortController();
      controller.abort(new DOMException('Request timed out after 25s', 'TimeoutError'));

      globalThis.fetch = async (_url, options) => {
        if (options?.signal?.aborted) {
          const err = new DOMException('The operation was aborted.', 'AbortError');
          throw err;
        }
        return new Response('{}', { status: 200 });
      };

      try {
        await apiFetch('/insights', { signal: controller.signal });
        assert.fail('apiFetch should have thrown');
      } catch (err) {
        assert.ok(err instanceof ApiError, 'Expected ApiError');
        assert.equal(err.status, 408);
        assert.equal(err.errorType, 'timeout_error');
        assert.ok(err.message.includes('timed out'));
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('translates aborted request into ApiError timeout_error (HTTP 408, not network_error)', async () => {
      const originalFetch = globalThis.fetch;
      const controller = new AbortController();
      controller.abort();

      globalThis.fetch = async () => {
        throw new DOMException('The user aborted a request.', 'AbortError');
      };

      try {
        await apiFetch('/insights', { signal: controller.signal });
        assert.fail('apiFetch should have thrown');
      } catch (err) {
        assert.ok(err instanceof ApiError, 'Expected ApiError');
        assert.equal(err.status, 408);
        assert.equal(err.errorType, 'timeout_error');
        assert.ok(!err.message.includes('ensure the backend service is running'));
      } finally {
        globalThis.fetch = originalFetch;
      }
    });

    it('preserves genuine network_error when fetch throws TypeError (connection lost)', async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async () => {
        throw new TypeError('Failed to fetch');
      };

      try {
        await apiFetch('/insights');
        assert.fail('apiFetch should have thrown');
      } catch (err) {
        assert.ok(err instanceof ApiError, 'Expected ApiError');
        assert.equal(err.status, 0);
        assert.equal(err.errorType, 'network_error');
        assert.ok(err.message.includes('Unable to connect to server'));
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });

  describe('2. ErrorState Resolution for Timeouts vs Offline', () => {
    it('renders "Request Timed Out" (NOT "Backend Service Offline") on timeout_error', () => {
      const markup = renderToStaticMarkup(
        React.createElement(ErrorState, {
          statusCode: 408,
          errorType: 'timeout_error',
          message: 'The operation was aborted.',
        })
      );

      assert.ok(markup.includes('Request Timed Out'), 'Title should be Request Timed Out');
      assert.ok(
        !markup.includes('Backend Service Offline'),
        'Must not display Backend Service Offline for timeouts'
      );
      assert.ok(markup.includes('HTTP 408'), 'Badge should show HTTP 408');
      assert.ok(markup.includes('The server took longer than expected to respond'));
    });

    it('renders "Backend Service Offline" only for actual network_error connection failures', () => {
      const markup = renderToStaticMarkup(
        React.createElement(ErrorState, {
          statusCode: 0,
          errorType: 'network_error',
          message: 'Unable to connect to server (Failed to fetch).',
        })
      );

      assert.ok(markup.includes('Backend Service Offline'));
      assert.ok(markup.includes('Unable to reach the GAP-AI service'));
    });
  });

  describe('3. CoachView Error State for Timeouts', () => {
    it('renders "Request timed out" heading when coach loading experiences timeout_error', () => {
      const dummyHandlers = {
        onRefresh: () => {},
        onShowAnother: () => {},
        onRate: () => {},
        onDismiss: () => {},
        onToggleWhy: () => {},
        onDurationInput: () => {},
        onDateInput: () => {},
        onTimeInput: () => {},
        onSaveDuration: () => {},
        onAddToPlans: () => {},
        onRequireAuth: () => {},
      };

      const markup = renderToStaticMarkup(
        React.createElement(CoachView, {
          state: {
            status: 'error',
            cards: [],
            busyId: null,
            ratings: {},
            whyOpen: {},
            durations: {},
            scheduledDates: {},
            scheduledTimes: {},
            notice: null,
            actionError: null,
            insights: null,
            error: {
              message: 'Request timed out waiting for insights. The server took too long to respond.',
              statusCode: 408,
              errorType: 'timeout_error',
            },
          },
          handlers: dummyHandlers,
        })
      );

      assert.ok(markup.includes('Request timed out'), 'Coach error heading should say Request timed out');
      assert.ok(!markup.includes('Backend Service Offline'));
      assert.ok(markup.includes('Retry'), 'Must offer retry action');
    });
  });

  describe('4. fetchInsights Timeout and Error Mapping', () => {
    it('translates fetch timeout/abort into timeout_error (HTTP 408)', async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async (_url, options) => {
        assert.ok(options?.signal, 'fetchInsights must pass signal to fetch');
        throw new DOMException('The operation was aborted.', 'AbortError');
      };

      try {
        await fetchInsights('week');
        assert.fail('should have thrown');
      } catch (err) {
        assert.ok(err instanceof ApiError);
        assert.equal(err.status, 408);
        assert.equal(err.errorType, 'timeout_error');
        assert.ok(err.message.includes('timed out'));
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });
});
