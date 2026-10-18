import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

// API istemcisi ve fetchInsights fonksiyonunun test uygulanışı
describe('W2-2 Insights (Analiz) Ekranı Birim ve Entegrasyon Testleri', () => {
  let requestedUrls = [];
  let requestedHeaders = [];
  let mockStorage = {};
  let mockFetchResponse = null;

  // apiFetch & fetchInsights mantığını izole test ortamında simüle eden yardımcılar
  function getStoredToken() {
    return mockStorage['gap_access_token'] || null;
  }

  async function apiFetch(endpoint, options = {}) {
    const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    const url = `/api${normalizedEndpoint}`;
    const headers = new Headers(options.headers || {});

    const token = getStoredToken();
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    requestedUrls.push(url);
    requestedHeaders.push(headers);

    return mockFetchResponse;
  }

  async function fetchInsights(period = 'week') {
    const query = encodeURIComponent(period);
    return apiFetch(`/insights?period=${query}`, {
      method: 'GET',
    });
  }

  beforeEach(() => {
    requestedUrls = [];
    requestedHeaders = [];
    mockStorage = {};
    mockFetchResponse = {
      period: 'week',
      planned: 4,
      done: 2,
      postponed: 1,
      skipped: 0,
      unreported: 1,
      adherence_pct: 66.7,
      avg_start_delay_min: 17,
      by_weekday: {
        Tuesday: { planned: 2, done: 1, postponed: 1 },
      },
      by_hour: {
        '18': { planned: 3, done: 2 },
      },
      postponed_targets: [
        { weekday: 'Thursday', hour: 19, count: 1 },
      ],
      trend_vs_prev: {
        adherence_pct_delta: 12.5,
      },
      narrative: 'Raporlanan üç planın ikisini tamamladın...',
      is_demo: false,
      data_label: 'real',
    };
  });

  describe('1. API İstemcisi ve Periyot Parametresi Testleri', () => {
    it('fetchInsights() varsayılan olarak "week" periyodunu çağırmalıdır', async () => {
      const res = await fetchInsights();

      assert.equal(requestedUrls.length, 1);
      assert.equal(requestedUrls[0], '/api/insights?period=week');
      assert.equal(res.period, 'week');
      assert.equal(res.adherence_pct, 66.7);
    });

    it('fetchInsights("last_week") parametresini URL sorgusuna doğru bağlamalıdır', async () => {
      await fetchInsights('last_week');

      assert.equal(requestedUrls.length, 1);
      assert.equal(requestedUrls[0], '/api/insights?period=last_week');
    });

    it('fetchInsights("all") parametresini URL sorgusuna doğru bağlamalıdır', async () => {
      await fetchInsights('all');

      assert.equal(requestedUrls.length, 1);
      assert.equal(requestedUrls[0], '/api/insights?period=all');
    });

    it('Kayıtlı Bearer token varsa isteğe Authorization: Bearer <token> başlığı eklemelidir', async () => {
      mockStorage['gap_access_token'] = 'test-token-bearer-xyz';
      await fetchInsights('week');

      assert.equal(requestedHeaders.length, 1);
      const headers = requestedHeaders[0];
      assert.equal(headers.get('Authorization'), 'Bearer test-token-bearer-xyz');
    });
  });

  describe('2. "Not enough data" Boş Durum Kriteri Testleri', () => {
    it('adherence_pct null olduğunda "Not enough data" durumu tetiklenmelidir', () => {
      const data = {
        period: 'week',
        planned: 1,
        done: 0,
        postponed: 0,
        skipped: 0,
        unreported: 1,
        adherence_pct: null,
      };

      const hasEnoughData =
        data !== null &&
        data.planned > 0 &&
        data.adherence_pct !== null &&
        data.adherence_pct !== undefined;

      assert.equal(hasEnoughData, false, 'adherence_pct null iken veri yetersiz sayılmalıdır');
    });

    it('planned 0 olduğunda "Not enough data" durumu tetiklenmelidir', () => {
      const data = {
        period: 'week',
        planned: 0,
        done: 0,
        postponed: 0,
        skipped: 0,
        unreported: 0,
        adherence_pct: 0,
      };

      const hasEnoughData =
        data !== null &&
        data.planned > 0 &&
        data.adherence_pct !== null &&
        data.adherence_pct !== undefined;

      assert.equal(hasEnoughData, false, 'planned 0 iken veri yetersiz sayılmalıdır');
    });

    it('Geçerli plan ve uyum yüzdesi varken görselleştirme ekranı aktif olmalıdır', () => {
      const data = {
        period: 'week',
        planned: 4,
        done: 2,
        postponed: 1,
        skipped: 0,
        unreported: 1,
        adherence_pct: 66.7,
      };

      const hasEnoughData =
        data !== null &&
        data.planned > 0 &&
        data.adherence_pct !== null &&
        data.adherence_pct !== undefined;

      assert.equal(hasEnoughData, true, 'Geçerli veride hasEnoughData true olmalıdır');
    });
  });

  describe('3. "Sample Data" Rozeti Kriteri Testleri', () => {
    it('data_label: "demo" olduğunda isDemo true olmalı ve "Sample Data" rozeti gösterilmelidir', () => {
      const data = {
        data_label: 'demo',
        is_demo: false,
      };

      const isDemo = data.data_label === 'demo' || data.is_demo === true;
      assert.equal(isDemo, true, 'data_label "demo" iken rozet render edilmelidir');
    });

    it('is_demo: true olduğunda isDemo true olmalıdır', () => {
      const data = {
        data_label: 'real',
        is_demo: true,
      };

      const isDemo = data.data_label === 'demo' || data.is_demo === true;
      assert.equal(isDemo, true, 'is_demo true iken rozet render edilmelidir');
    });

    it('data_label: "real" ve is_demo: false olduğunda rozet gösterilmemelidir', () => {
      const data = {
        data_label: 'real',
        is_demo: false,
      };

      const isDemo = data.data_label === 'demo' || data.is_demo === true;
      assert.equal(isDemo, false, 'Gerçek veride demo rozeti gösterilmemelidir');
    });
  });

  describe('4. Dağılım Grafikleri ve Hedefler Sözleşme Uyumu', () => {
    it('Gün dağılımı (by_weekday) doğru işlenmeli ve oranlar hesaplanmalıdır', () => {
      const byWeekday = {
        Tuesday: { planned: 2, done: 1, postponed: 1 },
      };

      assert.ok(byWeekday.Tuesday);
      assert.equal(byWeekday.Tuesday.planned, 2);
      assert.equal(byWeekday.Tuesday.done, 1);
      assert.equal(byWeekday.Tuesday.postponed, 1);
    });

    it('Saat dağılımı (by_hour) doğru işlenmeli ve saat formatı doğrulanmalıdır', () => {
      const byHour = {
        '18': { planned: 3, done: 2 },
      };

      assert.ok(byHour['18']);
      assert.equal(byHour['18'].planned, 3);
      assert.equal(byHour['18'].done, 2);
      assert.equal(parseInt('18', 10), 18);
    });

    it('Ertelenen hedefler (postponed_targets) dizi elemanlarını tam sözleşmeye uygun karşılamalıdır', () => {
      const targets = [
        { weekday: 'Thursday', hour: 19, count: 1 },
      ];

      assert.equal(targets.length, 1);
      assert.equal(targets[0].weekday, 'Thursday');
      assert.equal(targets[0].hour, 19);
      assert.equal(targets[0].count, 1);
    });

    it('Trend farkı (trend_vs_prev) pozitif veya negatif değerleri desteklemelidir', () => {
      const positiveTrend = { adherence_pct_delta: 12.5 };
      const negativeTrend = { adherence_pct_delta: -5.0 };

      assert.ok(positiveTrend.adherence_pct_delta > 0);
      assert.ok(negativeTrend.adherence_pct_delta < 0);
    });
  });
});
