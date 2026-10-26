# GAP-AI — Görev ve Durum Takibi

Bu dosya, depodaki mevcut kod ve yapılandırmaya göre güncellenir. **Kodda mevcut** ifadesi özelliğin uygulama dosyalarının bulunduğunu belirtir; canlı ortamda veya donanımda uçtan uca doğrulandığı anlamına gelmez. Dağıtım, gerçek servis bağlantısı ve fiziksel cihaz testi ayrıca kanıtlanmalıdır.

> Önceki ekip planı, tarihleri ve sorumlulukları için [GOREVLER_14-29_EKIM.md](GOREVLER_14-29_EKIM.md) tarihsel planlama belgesidir; bu dosyadaki durumların yerine geçmez.

## Depoda mevcut olanlar

- [x] **Backend API temeli:** FastAPI uygulaması, CORS ve standart hata yanıtları; `/health`, `/demo/session`, `/me`, `/plans`, `/plans/{id}/outcome`, `/parse`, `/voice`, `/me/upcoming`, `/insights` ve `/plans/{id}/suggestion` router'ları kayıtlıdır. Kaynak: `backend/app/main.py`.
- [x] **Plan ve sonuç veri erişimi:** Supabase PostgREST adaptörü, plan listeleme/oluşturma, sonuç olayları ve idempotent plan oluşturma kodu vardır. Kaynak: `backend/app/db/plans.py`, `backend/app/api/plans.py`, `backend/app/api/outcomes.py`.
- [x] **Demo akışı:** İzole demo oturumu ve sentetik plan/sonuç seed verisi kodlanmıştır. Kaynak: `backend/app/api/demo.py`, `backend/app/db/demo_seed.py`, `demo/seed/demo_plans.json`.
- [x] **Metinle plan oluşturma:** Nebius istemcisi ve `ParsedPlan` schema doğrulama/yeniden deneme akışı vardır. Kaynak: `backend/app/api/parse.py`, `backend/app/ai/llm.py`, `ai/schema.json`.
- [x] **Backend ses uç noktası:** `/voice`, yüklenen WAV dosyasını doğrular, Groq STT'ye gönderir ve `create_plan` sonucunu kaydeder. Kaynak: `backend/app/api/voice.py`, `backend/app/ai/stt.py`.
- [x] **Analiz ve öneri kodu:** Deterministik insights hesaplama, plan başına saklanan suggestion, behavior/discovery/contextual kart policy'si, kullanıcıya özel feedback, 3 kart sınırı ve 30 günlük dismissal vardır. Contextual kartlar yalnızca açık profil cevaplarını, gelecek planları ve gerçek hava durumu yanıtını kullanır; kaynakları UI'da gösterilir. Kaynak: `backend/app/analytics/insights.py`, `backend/app/api/insights.py`, `backend/app/api/suggestions.py`, `backend/app/recommendations.py`.
- [x] **My Plans suggestion entegrasyonu:** Plan başına suggestion otomatik sayfa yüklemesinde istenmez; kullanıcı talep edince kayıtlı suggestion yeniden kullanılır. Önerilen zaman değişikliği yalnızca onay sonrası mevcut `PUT /plans/{id}` endpoint'iyle kaydedilir. Plan sorting/filtering, edit/delete ve outcome butonları mevcut akışlarında kalır. Kaynak: `web/src/pages/PlanList.tsx`.
- [x] **Web uygulaması:** React arayüzünde demo oturumu, metinle plan oluşturma, plan listesi/sonuç bildirimi ve insights ekranı vardır. Kaynak: `web/src/`.
- [x] **Şema ve SQL doğrulama dosyaları:** Temel ve suggestions migration'ları ile SQL doğrulama betikleri ve GitHub Actions iş akışı vardır. Kaynak: `database/migrations/`, `database/tests/`, `.github/workflows/backend-tests.yml`.
- [x] **ESP32 başlangıç firmware'i ve ses kayıt modülü:** Wi-Fi bağlantısı, `/health` kontrolü ve bağımsız I2S/WAV kayıt kodu vardır. Kaynak: `esp32/main/`.

## Tamamlanması veya doğrulanması gerekenler

- [ ] **API sözleşmesi kapsamındaki eksik backend rotaları:** `POST /plans/{id}/reschedule`, `GET /me/export` ve `DELETE /me/data` sözleşmede tanımlı; mevcut FastAPI router'larında uygulanmamıştır. Kapsama dair karar verilmeden bunları tamamlanmış olarak işaretlemeyin. Ayrıntı: [api-contract.md](api-contract.md).
- [ ] **Tam backend test koşusu:** Backend pytest paketi CI'da çalışacak şekilde tanımlıdır; yerel/sandbox doğrulaması tam sonuç vermediyse CI sonucu kontrol edilip başarısızlıklar giderilmelidir.
- [ ] **Canlı veritabanı ve servis entegrasyonu:** Core, suggestions, suggestion refresh, personalization profile ve recommendation feedback migration'larının hedef Supabase projesinde uygulanması ve SQL doğrulamasının çalıştırılması gerekir. Depoda dosyaların bulunması migration'ın canlı projede uygulanmış olduğu anlamına gelmez. Nebius ve Groq çağrıları da geçerli servis kimlik bilgileriyle ayrıca doğrulanmalıdır.
- [ ] **ESP32 uçtan uca entegrasyonu:** `audio_record` 16 kHz mono, 16-bit PCM WAV kaydını en fazla 10 saniye ile sınırlar; fakat `main.c` yalnızca `/health` çağırır. `api.c` içinde multipart `/voice` yüklemesi veya yanıt JSON ayrıştırma yoktur. `DEVICE_TOKEN` örnek yapılandırmada boştur. CMake'de mevcut I2S bağımlılığı yalnızca `esp_driver_i2s`; TX/playback kodu, hoparlör/amfi tanımı, pin eşlemesi veya TTS ses kaynağı yoktur. Donanım ve mevcut TTS/playback kaynağı doğrulandıktan sonra: kaydı mevcut `/voice` sözleşmesiyle yükle, `spoken_recommendation` alanını boyut sınırlı oku ve onaylanan donanımla oynat; servis hatalarında güvenli metin/log geri dönüşü sağla. Donanım doğrulanmadan pin, kütüphane veya yeni endpoint varsayma.
- [ ] **Web ve backend dağıtım durumu:** `docs/DEPLOY.md` staging dağıtım talimatı verir; canlı URL ve çalışan deploy bilgisi bu depodan doğrulanamaz. Demo öncesi deploy ve tarayıcıdan uçtan uca akış kontrol edilmelidir.
- [ ] **Öneri zamanlama tercihi:** `recommendation_frequency=off` Insights kartlarını ve plan suggestion endpoint'ini bastırır. `daily`, `weekly` ve `on_demand` saklanır; repository'de zamanlayıcı olmadığı için bunlar otomatik teslimat başlatmaz.
- [ ] **Üretim öncesi işletim/güvenlik kontrolü:** Kimlik doğrulamasız demo session üretimi için kullanım sınırları ve web token saklama yaklaşımı gözden geçirilmelidir. `.env.example` içindeki değişkenler runtime'da okunan ayarlarla karşılaştırılmalıdır.

## Doğrulama kaydı

Doğrulama sonuçlarını, çalıştırılan komut ve tarih ile güncel tutun. Kaynak kodun veya test dosyasının bulunması tek başına başarılı test/entegrasyon kanıtı değildir. Şema ve SQL davranışı için backend testlerinin yanı sıra `.github/workflows/backend-tests.yml` içindeki PostgreSQL migration işi de izlenmelidir.
