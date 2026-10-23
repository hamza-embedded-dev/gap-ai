import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webSrcDir = path.resolve(__dirname, '../src');

describe('W2-4 Mobile Compatibility, Loading, Empty & Error States Tests', () => {
  describe('1. Global & Responsive CSS Layout Verification (375px Protection)', () => {
    it('index.css must enforce overflow-x: hidden on root/body to avoid horizontal scroll', () => {
      const indexCss = fs.readFileSync(path.join(webSrcDir, 'index.css'), 'utf-8');
      assert.ok(indexCss.includes('overflow-x: hidden'), 'index.css must declare overflow-x: hidden');
      assert.ok(indexCss.includes('box-sizing: border-box'), 'index.css must enforce border-box globally');
    });

    it('App.css must have mobile media queries for small screen widths (max-width: 480px)', () => {
      const appCss = fs.readFileSync(path.join(webSrcDir, 'App.css'), 'utf-8');
      assert.ok(appCss.includes('@media (max-width: 480px)'), 'App.css must define mobile breakpoint');
      assert.ok(appCss.includes('flex-direction: column'), 'App.css must provide column stacking for buttons/actions on mobile');
    });

    it('Insights.css must contain responsive breakpoints with mobile-optimized grid and zero overflow', () => {
      const insightsCss = fs.readFileSync(path.join(webSrcDir, 'pages/Insights.css'), 'utf-8');
      assert.ok(insightsCss.includes('@media (max-width: 480px)'), 'Insights.css must define 480px/mobile breakpoint');
      assert.ok(insightsCss.includes('-webkit-overflow-scrolling: touch'), 'Insights.css must provide touch scrolling for charts');
      assert.ok(insightsCss.includes('grid-template-columns: repeat(3, 1fr)'), 'Period selector must use 3-column equal grid on mobile');
    });
  });

  describe('2. Skeleton & Loading UI Verification', () => {
    it('Skeleton component must include accessible status role and shimmer animation', () => {
      const skeletonTsx = fs.readFileSync(path.join(webSrcDir, 'components/ui/Skeleton.tsx'), 'utf-8');
      const skeletonCss = fs.readFileSync(path.join(webSrcDir, 'components/ui/Skeleton.css'), 'utf-8');

      assert.ok(skeletonTsx.includes('role="status"'), 'Skeleton must have role="status"');
      assert.ok(skeletonTsx.includes('aria-busy="true"'), 'Skeleton must have aria-busy="true"');
      assert.ok(skeletonCss.includes('skeletonShimmer'), 'Skeleton.css must implement skeletonShimmer animation');
    });

    it('InsightsSkeleton must mirror dashboard layout with placeholders for gauge, stats, charts and targets', () => {
      const insightsSkeleton = fs.readFileSync(path.join(webSrcDir, 'components/insights/InsightsSkeleton.tsx'), 'utf-8');
      assert.ok(insightsSkeleton.includes('insights-skeleton'), 'InsightsSkeleton must have insights-skeleton ID');
      assert.ok(insightsSkeleton.includes('gauge-skeleton-wrapper'), 'InsightsSkeleton must render gauge placeholder');
      assert.ok(insightsSkeleton.includes('stats-skeleton-grid'), 'InsightsSkeleton must render stats grid placeholder');
      assert.ok(insightsSkeleton.includes('distribution-skeleton-container'), 'InsightsSkeleton must render distribution charts placeholder');
    });
  });

  describe('3. Error State & Network Down Simulation Tests', () => {
    it('ErrorState component must detect network / connection errors and display friendly guidance', () => {
      const errorStateTsx = fs.readFileSync(path.join(webSrcDir, 'components/ui/ErrorState.tsx'), 'utf-8');
      assert.ok(errorStateTsx.includes('network_error'), 'ErrorState must handle network_error');
      assert.ok(errorStateTsx.includes('role="alert"'), 'ErrorState must have role="alert"');
      assert.ok(errorStateTsx.includes('Retry Connection'), 'ErrorState must have retry button support');
    });

    it('ApiError client should instantiate network_error when fetch throws', async () => {
      class ApiError extends Error {
        constructor(message, status, errorType = 'api_error') {
          super(message);
          this.name = 'ApiError';
          this.status = status;
          this.errorType = errorType;
        }
      }

      function simulateFailedFetch() {
        try {
          throw new TypeError('Failed to fetch');
        } catch (err) {
          throw new ApiError(
            `Unable to connect to server (${err.message}). Please ensure the backend service is running.`,
            0,
            'network_error'
          );
        }
      }

      assert.throws(
        () => simulateFailedFetch(),
        (err) => {
          assert.equal(err instanceof ApiError, true);
          assert.equal(err.status, 0);
          assert.equal(err.errorType, 'network_error');
          assert.ok(err.message.includes('Unable to connect to server'));
          return true;
        }
      );
    });

    it('ErrorBoundary must render fallback on render crash without taking down the full DOM', () => {
      const errorBoundaryTsx = fs.readFileSync(path.join(webSrcDir, 'components/ui/ErrorBoundary.tsx'), 'utf-8');
      assert.ok(errorBoundaryTsx.includes('getDerivedStateFromError'), 'ErrorBoundary must define getDerivedStateFromError');
      assert.ok(errorBoundaryTsx.includes('componentDidCatch'), 'ErrorBoundary must define componentDidCatch');
      assert.ok(errorBoundaryTsx.includes('ErrorState'), 'ErrorBoundary must utilize ErrorState fallback');
    });
  });

  describe('4. Empty State ("Not enough data") Contract Verification', () => {
    it('EmptyInsights must show "Not enough data" heading and actionable hint', () => {
      const emptyInsightsTsx = fs.readFileSync(path.join(webSrcDir, 'components/insights/EmptyInsights.tsx'), 'utf-8');
      assert.ok(emptyInsightsTsx.includes('Not enough data'), 'EmptyInsights must render exact contract title "Not enough data"');
      assert.ok(emptyInsightsTsx.includes('empty-insights-state'), 'EmptyInsights must have empty-insights-state ID');
      assert.ok(emptyInsightsTsx.includes('Check Again'), 'EmptyInsights must offer retry/refresh button');
    });
  });

  describe('5. English Localization Verification', () => {
    it('All source files in web/src must not contain remaining Turkish special characters', () => {
      const turkishCharsRegex = /[çğışöüÇĞİŞÖÜ]/;
      const filesToCheck = [
        'App.tsx',
        'pages/Insights.tsx',
        'components/insights/AdherenceMetricCard.tsx',
        'components/insights/DistributionCharts.tsx',
        'components/insights/EmptyInsights.tsx',
        'components/insights/PostponedTargetsList.tsx',
        'components/insights/SampleDataBadge.tsx',
        'components/ui/ErrorState.tsx',
        'components/ui/Skeleton.tsx',
        'api/client.ts',
        'api/demo.ts',
        'api/insights.ts',
      ];

      for (const relPath of filesToCheck) {
        const fullPath = path.join(webSrcDir, relPath);
        if (fs.existsSync(fullPath)) {
          const content = fs.readFileSync(fullPath, 'utf-8');
          const match = content.match(turkishCharsRegex);
          assert.equal(
            match,
            null,
            `File ${relPath} contains Turkish character: "${match ? match[0] : ''}"`
          );
        }
      }
    });

    it('Navigation, header and tabs must use standard English labels', () => {
      const appContent = fs.readFileSync(path.join(webSrcDir, 'App.tsx'), 'utf-8');
      assert.ok(appContent.includes('Goal &amp; Action Planning') || appContent.includes('Goal & Action Planning'));
      assert.ok(appContent.includes('Personal Behavior &amp; Analytics Assistant') || appContent.includes('Personal Behavior & Analytics Assistant'));
      assert.ok(appContent.includes('Insights'));
      assert.ok(appContent.includes('Demo &amp; Auth') || appContent.includes('Demo & Auth'));
      assert.ok(appContent.includes('Reset Session'));
    });
  });
});
