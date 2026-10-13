# GAP-AI Görev Listesi: 14–29 Ekim 2026

Bu plan, projenin mevcut kod durumu, veritabanı migration'ları ve sözleşme analizine göre hazırlanmıştır. Ekip üyeleri kendi kodlarını (B1, W2, D1 vb.) aratarak doğrudan sorumluluklarını, branch isimlerini ve teslim tarihlerini takip edebilir.

---

## 1. Temel Takvim ve Çalışma Kuralları

| Tarih | Kilometre Taşı | Açıklama |
|---|---|---|
| **14 Ekim (Çarşamba)** | **Çalışma Başlangıcı** | Tüm ekip branch'lerini açar. E (Entegratör) onaylanan kararları ve açık konuları ekiple paylaşır. |
| **14–18 Ekim** | **Öncelikli Özellikler (P0 & P1)** | Gate 1 çekirdeği tamamlanır. 18 Ekim akşamı staging ortamında ilk uçtan uca akış test edilir. |
| **19 Ekim (Pazartesi)** | **Feature Freeze** | Yeni özellik alımı durdurulur (`v0.9.0-freeze`). Bu tarihten sonra yalnızca hata düzeltmesi kabul edilir. |
| **20–25 Ekim** | **Entegrasyon ve Test** | Hata giderme, staging ve Netlify canlı ortamı, donanım optimizasyonu. |
| **26 Ekim (Pazartesi)** | **Release / Code Freeze** | Kod dondurulur (`v1.0.0`). Yalnızca kritik bloklayıcı yamalar alınır. |
| **27–29 Ekim** | **Demo ve Teslim** | Video kurgusu, Devpost İngilizce metni ve son kontroller. **Hedef gönderim: 29 Ekim.** (30 Ekim yedek gündür). |

> **Önemli Kural (P0 Taahhüdü ve P1 Hedef Tarihleri Ayrımı):**
> - **P0 Görevleri:** Gate 1 çekirdeğini oluşturan zorunlu ve garantili teslimatlardır; dondurma öncesi tamamlanmaları şarttır.
> - **P1 Görevleri (Öneri, Reschedule, Upcoming vb.):** Görevlerde belirtilen bitiş tarihleri 19 Ekim Feature Freeze öncesi ulaşılması hedeflenen **çalışma hedefleridir (target dates)**; kesin garanti edilmiş teslimat taahhüdü değildir. Herhangi bir teknik risk anında P0 çekirdek akışının kararlılığı önceliklidir.

### Çalışma Yöntemi (8 Adım)
1. `main` dalından güncel kodu çek: `git checkout main && git pull`
2. Görevine uygun branch aç: `git checkout -b <rol>/<kisa-ad>` (Örnek: `b1/get-plans`)
3. Görevini, `docs/api-contract.md` ve `ai/schema.json` dosyalarını incele.
4. ChatGPT ile yapacağın adımları netleştir (gizli anahtar ve token yapıştırma).
5. Antigravity ile kodunu geliştir.
6. Testleri yerelde çalıştır: `cd backend && uv run --extra dev pytest` (veya `npm run build`).
7. Commit at (`feat: ...`, `fix: ...`, `test: ...`) ve push yap.
8. Pull Request aç, PR şablonunu doldur; CI yeşil olunca ve inceleme tamamlanınca merge'i bekle. Doğrudan `main`'e push yasaktır.

### 1.1 Zorunlu İlk Gün Kurulumu: Yerel Ortam (.env) ve Rol Bazlı Gizlilik Kuralları (Tüm Ekip)

Projeye katkı veren her ekip üyesi 14 Ekim tarihinde geliştirmeye başlamadan önce aşağıdaki adımları yerel ortamında tamamlamakla yükümlüdür:

1. **Yerel `.env` Dosyası Oluşturma**:
   - Depo kökündeki `.env.example` dosyasını kopyalayarak yerel `.env` dosyanı oluştur:
     ```bash
     cp .env.example .env
     ```
2. **Rol Bazlı ve En Az Ayrıcalıklı (Least Privilege) Kimlik Bilgisi Yapılandırması**:
   - **`SUPABASE_SERVICE_KEY` ASLA TÜM EKİBE DAĞITILMAZ:** RLS ve güvenlik kurallarını tamamen devre dışı bırakan bu süper yetkili anahtar, yalnızca veritabanı adaptörünü yazan ve migration çalıştıran **B3 (Ece Ulvi)** ile sunucu dağıtımını yapan **E (Hamza Yüksel)** tarafından backend yerel ortamında kullanılır.
   - **Web UI Ekibi (W1, W2):** Veritabanı servis anahtarı, Nebius veya Groq anahtarı **ALMAZ**. Yalnızca genel istemci yapılandırmasını (backend API adresi `http://localhost:8000` veya staging URL) kullanır.
   - **Donanım Ekibi (D1, D2):** Veritabanı servis anahtarı **ALMAZ**. Yalnızca yerel Wi-Fi bilgileri ve B3-3 scriptiyle üretilen cihaz Bearer test token'ını `secrets.h` dosyasında tutar.
   - **Backend / AI (B2, B5):** B2 yalnızca Nebius anahtarını, B5 yalnızca Groq anahtarını alır.
   - Hiçbir geliştiriciye rolünün gerektirdiğinden fazla sır verilmez.
3. **Gerekli Değişkenlerin Varlığını Doğrulama**:
   - Kodunu çalıştırmadan önce rolünle ilgili tüm ortam değişkenlerinin tanımlı ve eksiksiz olduğunu doğrula.
4. **Yerel Sağlık Kontrolü / Duman Testi (Smoke Test)**:
   - Backend için: `cd backend && uv run pytest tests/test_health.py` çalıştır veya `uv run python -m uvicorn app.main:app --port 8000` başlatıp `curl http://localhost:8000/health` ile HTTP 200 yanıtı al.
   - Web için: `cd web && npm run build` ile yerel derlemeyi doğrula.
   - Donanım için: `esp32/include/secrets.example.h` dosyasını `secrets.h` olarak kopyala ve derleme al.
5. **Kesin Güvenlik ve Gizlilik Kuralları**:
   - `.env`, `secrets.h`, gerçek API anahtarları, service-role anahtarları veya özel token'lar **ASLA** git'e commit edilmeyecektir (`.gitignore` dosyasında yer aldığından emin ol).
   - Gizli anahtarlar, veritabanı şifreleri veya token değerleri **ASLA** GitHub issue'larına, Pull Request başlık/açıklama/yorumlarına, kaynak kod dosyalarına veya ortak belgelere yapıştırılmayacaktır.
   - Depoya ve belgelere hiçbir zaman gerçek anahtar değerleri yazılmaz.
6. **Yerel Kurulum ve Paylaşılan Staging Sunucusu Ayrımı**:
   - Bu adımlar her geliştiricinin kendi bilgisayarında izole bir yerel test ortamı kurması içindir.
   - Paylaşılan merkezi bir staging sunucusunun kurulumu ve dağıtımı Hamza (E-5) tarafından yürütülecektir; yerel kurulum staging dağıtımı ile karıştırılmamalıdır.
   - Dış entegrasyonlar (Nebius, Supabase, Groq vb.) yerelde fiilen test edilip doğrulanana kadar her anahtarın sorunsuz çalıştığı veya her dış servisin erişilebilir olduğu varsayılmamalıdır.

### Dosya Çakışmalarını Önleme
- **`backend/app/db/plans.py`**: Önce **B3** (B3-1) temel metotları ekler ve 15 Ekim akşamı merge eder. B1 ve B4 ancak bu merge sonrası kendi sorgularını ekler.
- **`backend/app/api/plans.py`**: Yalnızca **B1** tarafından düzenlenir. B4 sonuç endpoint'ini `api/outcomes.py` dosyasına yazar.
- **`backend/app/main.py`**: Yeni router ekleyen herkes yalnızca kendi `include_router` satırını ekler; PR açmadan önce `main`'i merge eder.
- **`backend/app/config.py`**: Önce **B2** LLM ayarlarını ekler; ardından **B5** STT ayarlarını ekler.
- **`web/`**: Temel Vite + React yapısını **W1** (W1-1) kurar (15 Ekim); **W2** tasarım bileşenlerini bu yapı üzerine inşa eder.
- **`esp32/`**: Temel firmware ve Wi-Fi iskeletini **D1** (D1-1) kurar; **D2** mikrofon fonksiyonlarını ayrı modülde yazar.

---

## 2. Açık Konuların Durumu (K-1 – K-10 ve Rescheduling)

### A. Onaylanmış Mimari ve Kapsam Kararları (Confirmed Decisions)

| No | Konu | Karar | Gerekçe | Etkilenen Görevler |
|---|---|---|---|---|
| **K-1** | Başka kullanıcının planına erişim | `404 not_found` dönülür (`{"error": "not_found", "message": "Kaynak bulunamadı."}`) | ID enumeration saldırılarını ve diğer kullanıcıların plan UUID varlığını ifşa etmeyi önler. D-001 ve `api-contract.md:24` ile tam uyumludur. | B4-1, B1-1, B1-5 |
| **K-2** | Token temin mimarisi | İdari CLI scripti: `backend/scripts/create_access_token.py`. **(Not: Script henüz mevcut değildir; B3-3 görevi kapsamında geliştirilip test edilecektir).** | Halka açık kontrolsüz kayıt uç noktası açılmaz. Ham token ekranda bir kez üretilir; veritabanında yalnızca hash + pepper saklanır (D-002). | B3-3, D1-2 |
| **K-3** | `POST /voice` plan source değeri | `source: "voice"` | Girdi modalitesini yansıtır. Migration `plans_source_check` (`text`, `voice`, `device`) ile tam uyumludur. | B5-2, D2-2 |
| **K-5** | Öneri / Suggestions ve Hava Durumu | **MVP Kapsamında Onaylandı (Hamza):** İlk uygun istekte hava durumu (minimal hava durumu kontrolü/Open-Meteo) ve geçmiş veriye bakılarak öneri üretilir ve veritabanına kaydedilir. Sonraki isteklerde kayıtlı öneri döndürülür. | D-009 ve `api-contract.md:213-242` gereksinimidir. `{"suggestion": null}` yanıtı **yalnızca belgelenmiş alan koşullarında** (yetersiz veri veya erteleme gerektirmeyen elverişli hava koşulları) geçerlidir; onaylanan MVP öneri akışını uygulamak yerine bir kestirme veya ikame olarak kullanılamaz. Teknik bir engel çıkarsa belgelenir ve fallback sunulur; özellik sessizce silinmez. | B2-4, B3-7 |
| **Reschedule** | `POST /plans/{id}/reschedule` | **MVP Kapsamında Onaylandı (Hamza):** Plan zamanı (`planned_start`, `planned_end`) güncellenirken, `public.outcomes` tablosuna `status: 'postponed'`, `postponed_to: new_start` ve `note` alanına orijinal plan zamanı (`"Rescheduled from <old_start>..<old_end>. Reason: <reason>"`) kaydedilir. | Sözleşme:259-273 gereksinimidir. **Şema Analizi:** `outcomes` tablosunda `original_start` sütunu bulunmadığından, önceki zaman `note` alanında saklanarak ve ilk oluşturma zamanı `plan_creation_requests.response_snapshot` içinde tutularak denetim izi sıfır şema değişikliğiyle tam olarak korunur. | B1-5 |
| **K-6** | Ortak test kimlik bilgileri ve rol bazlı erişim | Hamza ortak test anahtarlarını temin etmiştir. `SUPABASE_SERVICE_KEY` (service-role) **ASLA tüm ekibe (Web/Donanıma) dağıtılmaz**; yalnızca DB adaptörü (B3) ve sunucu dağıtımında (E) kullanılır. Web ve Donanım yalnızca genel istemci yapılandırmasını alır. | En az ayrıcalık (least privilege) kuralı. Gerçek anahtarlar repoya girmez; her üye kendi yerel ortamında doğrular. Staging sağlayıcısı/URL dağıtımda (E-5) netleşir. | E-3, Tüm Ekip |
| **K-7** | Ses sözleşmesi ve web önceliği | Ses sözleşmesi (mono WAV 16 kHz 16-bit <=10s) ortaktır. Web'de metin girişi (`POST /parse`) P0 birincil akıştır; tarayıcıdan ses kaydı web teslimini riske atmamak adına P2 opsiyonel eklentidir. | Web öncelikli demoda metin girişi ana omurgadır (D-009). Tarayıcıda WAV kodlama işi web teslimini geciktirmemelidir. | W1-2, B5-2 |
| **K-8** | İstatistik saat dilimi ve hafta sınırı | Kullanıcının kayıtlı IANA saat dilimi esastır (D-010). Hafta Pazartesi 00:00:00 başlar ve Pazar 23:59:59 biter. | ISO 8601 standardı ve D-010 kararı ile uyumludur. `GET /insights` deterministiktir. | B1-3, V1-3 |
| **K-9** | Demo videosu teslim sahipliği | **Hamza Yüksel ve Ahmet Zeren ortak sahipliğindedir.** Burak Varol (B5) video sorumluluğundan çıkarılmıştır. Ahmet çalışan donanım çekimlerini yapar, Hamza YouTube/Devpost teslimini yürütür; kurgu ve seslendirme aralarındaki koordinasyonla yürütülür. | Burak Varol'un Whisper STT'ye tam odaklanması sağlanır; video gerçek çalışan arayüz ve donanımı yansıtır. | E-10, D1-5, W2-5 |
| **K-10** | Eski dokümantasyon ayrımı | `database/api-docs/` altındaki belgeler geçmiş tasarım referansıdır; tek otorite `docs/api-contract.md` ve `ai/schema.json`'dır. | `POST /device/telemetry` gibi sözleşmede yer almayan uç noktaların geliştirilmesi engellenir. | E-1, Tüm Ekip |

### B. Önerilen İşletimsel Varsayılanlar (Proposed Operational Defaults)

| No | Konu | Önerilen Varsayılan Kural | Sözleşme / Karar Durumu | Açıklama |
|---|---|---|---|---|
| **K-4** | Yaklaşan planlar ve hatırlatma ofseti | `reminder_at = planned_start - 15 dakika`. Parametre verilmezse `since = now()`, `to = now() + 24 saat`. | **Önerilen İşletimsel Varsayılandır:** Sözleşme metninde normatif kural yazılmamış, örnek JSON payload'ından türetilmiştir. | Yetkili sözleşmede aksi belirtilmediği sürece backend (B1-2) ve cihaz (D1-2) bu varsayılanları kullanır. Otomatik push scheduler yoktur, pull-based çalışır. |


---

## 3. Kişi Bazlı Görev Listesi

### E — Hamza Yüksel (Entegrasyon & Proje Koordinasyonu)

- **E-1 · D-011 Kararlarını ve K-10 Notunu Belgele**
  - **İş:** `docs/decisions.md` dosyasına onaylanan D-011 kararlarını işle; `database/api-docs/` belgelerinin başına "Geçmiş referans belgesidir, otorite `api-contract.md`'dir" notunu ekle.
  - **Tarih:** 14 Ekim → 14 Ekim | **Bağımlılık:** Yok
  - **Dosyalar:** `docs/decisions.md`, `database/api-docs/FastAPI_SCHEMA.md`, `database/api-docs/AI_SCHEMA.md`
  - **Branch / PR:** `E/docs/d011-decisions` | `docs: document D-011 decisions and legacy doc notices`
  - **Kriter:** Kararlar netleşti, dokümanlar güncellendi.
- **E-2 · Güncel Görev Listesini Yayınla**
  - **İş:** `docs/GOREVLER_14-29_EKIM.md` dosyasını `main`'e al; `.github/CODEOWNERS` dosyasını ekiple güncelle.
  - **Tarih:** 14 Ekim → 14 Ekim | **Bağımlılık:** Yok
  - **Dosyalar:** `docs/GOREVLER_14-29_EKIM.md`, `docs/TASKS.md`, `.github/CODEOWNERS`
  - **Branch / PR:** `E/docs/tasks-14-29-oct` | `docs: publish 14-29 October team task plan`
  - **Kriter:** Ekip yeni görev listesini onayladı.
- **E-3 · Ortak Test Kimlik Bilgilerini Dağıt ve Yerel .env Kurulumunu Doğrula**
  - **İş:** Hamza'nın temin ettiği test kimlik bilgilerini **rol bazlı en az ayrıcalık (least privilege)** kuralına göre dağıt:
    - `SUPABASE_SERVICE_KEY` sunucu/admin anahtarını **asla Web ve Donanım geliştiricilerine verme**; yalnızca B3 ve E ortamında tut.
    - W1 ve W2'ye yalnızca yerel backend API adresini bildir.
    - D1 ve D2'ye yalnızca Wi-Fi bilgileri ve provizyon edilmiş test bearer token'ını ilet.
    - B2'ye Nebius, B5'e Groq anahtarlarını ilet.
    Her üyenin Bölüm 1.1'deki adımları izleyerek kendi yerel `.env` dosyasını oluşturmasını ve yerel duman testini (smoke test) çalıştırmasını koordine et. Git'e gizli anahtar commit edilmesini ve GitHub'a yapıştırılmasını kesin olarak denetle.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** K-6
  - **Dosyalar:** `.env.example`
  - **Branch / PR:** Gerekmez (özel kanal paylaşımı).
  - **Kriter:** Geliştiriciler yalnızca kendi rollerine ait sırları alarak yerel ortamlarını kurdu; depoya hiçbir yetkisiz sır sızmadı.
- **E-4 · Backend Dockerfile Hazırla**
  - **İş:** FastAPI backend'i için Dockerfile ve `.dockerignore` oluştur; `uvicorn app.main:app` ile çalıştırılabilir yap.
  - **Tarih:** 15 Ekim → 16 Ekim | **Bağımlılık:** Yok
  - **Dosyalar:** `backend/Dockerfile` (yeni), `backend/.dockerignore` (yeni)
  - **Branch / PR:** `E/chore/backend-dockerfile` | `chore(backend): add container Dockerfile`
  - **Kriter:** `docker build` ve `docker run` yerelde 200 health yanıtı verdi.
- **E-5 · Staging Dağıtım Kılavuzu ve Ortam Kurulumu**
  - **İş:** Backend'i Nebius veya staging sunucusuna kur; web adresini CORS'a ekle; kurulum adımlarını belgele.
  - **Tarih:** 17 Ekim → 18 Ekim | **Bağımlılık:** E-4, B3-2
  - **Dosyalar:** `docs/DEPLOY.md` (yeni)
  - **Branch / PR:** `E/docs/staging-deploy` | `docs: add staging deployment guide`
  - **Kriter:** Canlı staging adresinden `GET /health` 200 dönüyor.
- **E-6 · Gate 1 Uçtan Uca Doğrulama ve Feature Freeze**
  - **İş:** Staging'de Parse -> Plan -> Outcome -> Insights akışını test et. `v0.9.0-freeze` etiketini oluştur.
  - **Tarih:** 18 Ekim → 19 Ekim | **Bağımlılık:** Tüm P0 görevleri
  - **Dosyalar:** `README.md`
  - **Branch / PR:** `E/docs/freeze-status` | `docs: record feature freeze status`
  - **Kriter:** Çekirdek akış çalışıyor; dondurma etiketi atıldı.
- **E-7 · Eski Prototip Dosyasını Temizle**
  - **İş:** Kök dizindeki `gemini-code-1791624011543.py` prototip dosyasını repo dışına al/sil.
  - **Tarih:** 20 Ekim → 20 Ekim | **Bağımlılık:** B1 onayı
  - **Dosyalar:** `gemini-code-1791624011543.py`, `README.md`
  - **Branch / PR:** `E/chore/remove-prototype` | `chore: remove unused prototype script`
  - **Kriter:** Dosya silindi, CI testleri sorunsuz geçti.
- **E-8 · Canlı Dağıtım Takibi ve PR İncelemeleri**
  - **İş:** Staging ortamını jüri için kalıcı demo ortamına dönüştür; tüm PR'ları 24 saat içinde incele ve merge et.
  - **Tarih:** 20 Ekim → 25 Ekim | **Bağımlılık:** W2-3
  - **Dosyalar:** `docs/DEPLOY.md`
  - **Branch / PR:** `E/docs/production-deploy` | `docs: finalize production deployment`
  - **Kriter:** Backend ve Netlify frontend kesintisiz canlıda.
- **E-9 · İngilizce README ve Release Freeze**
  - **İş:** README'yi teslim formatında İngilizce olarak tamamla (kurulum, mimari mermaid şeması, model kullanımı). `v1.0.0` etiketini at.
  - **Tarih:** 23 Ekim → 26 Ekim | **Bağımlılık:** V1-5
  - **Dosyalar:** `README.md`, `docs/ARCHITECTURE.md`
  - **Branch / PR:** `E/docs/final-readme` | `docs: finalize README for hackathon submission`
  - **Kriter:** README eksiksiz; kod donduruldu.
- **E-10 · Demo Video Teslimi ve YouTube Yüklemesi (Hamza Yüksel & Ahmet Zeren Ortak Sorumluluğu)**
  - **İş:** Demo videosu teslimini Ahmet Zeren (D1-5) ile ortaklaşa yönet:
    - Ahmet çalışan ESP32 donanımının, butonlarının ve OLED ekranının net çekimlerini sağlar.
    - Sevde (W2-5) canlı web arayüzünün ekran kayıtlarını iletir.
    - Video senaryosu, seslendirme (narration), kurgu ve montaj Hamza ve Ahmet arasındaki ortak koordinasyonla yürütülür (üzerinde anlaşılmamış bir alt iş bölümü uydurulmaz).
    - 2–3 dakikalık, yalnızca gerçek çalışan donanım ve web arayüzünü gösteren, İngilizce altyazılı nihai videoyu YouTube'a herkese açık yükle; linki teslim materyallerine ekle. Telifli müzik veya üçüncü taraf marka kullanma.
  - **Tarih:** 27 Ekim → 28 Ekim | **Bağımlılık:** W2-5, D1-5, K-9
  - **Dosyalar:** Repo dışı (YouTube linki)
  - **Kriter:** YouTube linki hazır; videoda yalnızca gerçek çalışan sistem gösteriliyor.
- **E-11 · Devpost Proje Gönderimi**
  - **İş:** Devpost proje metnini gir, video linkini (E-10) ekle, İngilizce dokümanları kontrol et ve 29 Ekim'de başvuruyu tamamla.
  - **Tarih:** 28 Ekim → 29 Ekim | **Bağımlılık:** E-9, E-10
  - **Dosyalar:** Repo dışı (Devpost)
  - **Kriter:** Devpost gönderim onayı alındı.

---

### B3 — Ece Ulvi (Veritabanı Adaptörü ve Oturumlar)

- **B3-1 · Plan Listeleme ve Outcome Adaptör Metotları (P0 - Kritik)**
  - **İş:** `PlanStore`, `SupabasePlanStore` ve `LazyPlanStore` sınıflarına `list_plans(user_id, from, to)`, `get_plan(user_id, plan_id)` ve `create_outcome(...)` metotlarını ekle. Her planla birlikte `latest_outcome` alanını döndür.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** Yok (B1-1 ve B4-1 bu işi bekler!)
  - **Dosyalar:** `backend/app/db/plans.py`, `backend/tests/test_plans.py`
  - **Branch / PR:** `b3/plan-outcome-store` | `feat(db): add plan listing and outcome store methods`
  - **Kriter:** MockTransport testleri sorguda daima `user_id=eq.<id>` filtresini doğruluyor; CI yeşil.
- **B3-2 · Migration'ı Gerçek Supabase'e Uygula (P0)**
  - **İş:** `database/migrations/20261013_001_gate1_core.sql` migration'ını Supabase panelinden çalıştır. `verify_gate1_core.sql` dosyasını gerçek DB'de çalıştırma (test kullanıcıları kalır). Kurulum notlarını ekle.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** E-3
  - **Dosyalar:** `backend/README.md`
  - **Branch / PR:** `b3/docs/supabase-setup` | `docs(db): document Supabase migration execution`
  - **Kriter:** Supabase panelinde 5 tablo hazır; yerel backend gerçek Supabase'e yazabiliyor.
- **B3-3 · İdari Erişim Tokenı Üretim Scriptini Geliştir ve Test Et (P1)**
  - **İş:** ESP32 ve test kullanıcıları için token basan CLI scriptini sıfırdan yaz (`backend/scripts/create_access_token.py`). Ham tokenı yalnız bir kez konsola yazdır, veritabanına yalnızca hash + pepper kaydet. **(Not: Script repoda henüz yoktur, bu görevde oluşturulacaktır).**
  - **Hedef Tarih:** 16 Ekim → 16 Ekim | **Bağımlılık:** K-2
  - **Dosyalar:** `backend/scripts/create_access_token.py` (yeni), `backend/tests/test_plan_auth.py`
  - **Branch / PR:** `b3/access-token-script` | `feat(db): add admin token generator script`
  - **Kriter:** Script çalıştırıldığında dönen token ile `POST /plans` isteği 200/201 dönüyor; testler geçiyor.
- **B3-4 · Demo Oturumuna Başlangıç Verisi (Seed) Ekleme (P0)**
  - **İş:** `POST /demo/session` çağrıldığında izole demo kullanıcısına V1'in hazırladığı 3-4 haftalık plan ve sonuç verilerini otomatik ekle.
  - **Tarih:** 16 Ekim → 17 Ekim | **Bağımlılık:** V1-1, B3-1
  - **Dosyalar:** `backend/app/db/plans.py`, `backend/app/api/demo.py`, `demo/seed/demo_plans.json`
  - **Branch / PR:** `b3/demo-seed` | `feat(demo): seed sample history on demo session creation`
  - **Kriter:** Yeni demo tokenı ile `GET /plans` çağrılınca örnek planlar dönüyor.
- **B3-5 · Profil Uç Noktaları: `GET /me` ve `PATCH /me` (P1)**
  - **İş:** Kullanıcı profilini okuma ve `timezone` / `display_name` güncelleme uç noktalarını yaz. Geçersiz IANA timezone için `422 validation_error` dön.
  - **Hedef Tarih:** 18 Ekim → 19 Ekim | **Bağımlılık:** B3-1
  - **Dosyalar:** `backend/app/api/me.py` (yeni), `backend/app/main.py`, `backend/tests/test_me.py` (yeni)
  - **Branch / PR:** `b3/me-profile` | `feat(api): add GET and PATCH /me endpoints`
  - **Kriter:** Profil okuma ve güncelleme testleri geçiyor, 401 ve 422 doğrulanıyor.
- **B3-6 · Veritabanı Hata Düzeltmeleri**
  - **İş:** Staging ve test sürecinde çıkan veritabanı sorgu hatalarını düzelt; demo veri birikimini denetle.
  - **Tarih:** 20 Ekim → 25 Ekim | **Bağımlılık:** V1-5
  - **Dosyalar:** `backend/app/db/plans.py`
  - **Branch / PR:** `b3/fix-db-issues` | `fix(db): resolve database adapter edge cases`
  - **Kriter:** Açık DB issue'ları kapatıldı.
- **B3-7 · Öneri Kalıcılığı Desteği (P1 - MVP Onaylı)**
  - **İş:** Hamza'nın nihai onayıyla MVP kapsamında uygulanır (D-009 ve `api-contract.md:213-242`):
    - `PlanStore` protokolüne ve adaptörlerine (`SupabasePlanStore`, test içi mock store) `get_suggestion(user_id, plan_id)` ve `save_suggestion(user_id, plan_id, suggestion_data)` metotlarını ekle.
    - İlk çağrıda üretilen önerinin kaydedilmesini, sonraki çağrılarda aynı önerinin okunabilmesini sağla.
    - Tenant izolasyonunu (`user_id`) eksiksiz koru.
  - **Hedef Tarih:** 18 Ekim → 19 Ekim | **Bağımlılık:** B3-1
  - **Dosyalar:** `backend/app/db/plans.py`, `backend/tests/test_plans.py`
  - **Branch / PR:** `b3/suggestion-storage` | `feat(db): add persistence support for suggestions`
  - **Kriter:** Öneri DB'ye yazılıp tekrar okunabiliyor; tenant izolasyonu korunuyor; testler geçiyor.

---

### B1 — Hamza Fatih (FastAPI Plan & İstatistik Endpoint'leri)

- **B1-1 · `GET /plans` Uç Noktası (P0)**
  - **İş:** Giriş yapan kullanıcının planlarını `from` ve `to` filtreleriyle listele. Sıralama `planned_start` artan olsun. Her planda `latest_outcome` alanı bulunsun.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** B3-1 (merge edilene kadar sahte store ile çalışır)
  - **Dosyalar:** `backend/app/api/plans.py`, `backend/tests/test_plans.py`
  - **Branch / PR:** `b1/get-plans` | `feat(api): implement GET /plans endpoint`
  - **Kriter:** 401 kontrolü, başka kullanıcının planlarının filtrelenmesi ve tarih aralığı testleri yeşil.
- **B1-2 · `GET /me/upcoming` Uç Noktası (P1)**
  - **İş:** Cihaz ve web için yaklaşan planları listele. Önerilen varsayılan kural: `reminder_at = planned_start - 15 dakika`, varsayılan aralık `now()` ile `now() + 24 saat` (K-4).
  - **Hedef Tarih:** 16 Ekim → 16 Ekim | **Bağımlılık:** B3-1, K-4
  - **Dosyalar:** `backend/app/api/upcoming.py` (yeni), `backend/app/main.py`, `backend/tests/test_upcoming.py` (yeni)
  - **Branch / PR:** `b1/me-upcoming` | `feat(api): implement GET /me/upcoming endpoint`
  - **Kriter:** Sözleşmedeki JSON formatında liste dönüyor; testler geçiyor.
- **B1-3 · `GET /insights` Deterministik GAP Analiz Motoru (P0 - Gate 1 Sonu)**
  - **İş:** Sözleşmedeki alanları hesaplayan saf Python analiz motorunu yaz: `planned`, `done`, `postponed`, `skipped`, `unreported`, `adherence_pct`, `avg_start_delay_min`, `by_weekday`, `by_hour`, `by_category`, `postponed_targets`.
    - Hafta Pazartesi 00:00 başlar (K-8).
    - Uyum hesabında planın son sonucu baz alınır.
    - Uygun geçmiş plan yoksa `adherence_pct: null` döner. `narrative: null` döner.
  - **Tarih:** 17 Ekim → 19 Ekim | **Bağımlılık:** B3-1, V1-3, K-8
  - **Dosyalar:** `backend/app/analytics/insights.py` (yeni), `backend/app/api/insights.py` (yeni), `backend/app/main.py`, `backend/tests/test_insights.py` (yeni)
  - **Branch / PR:** `b1/insights` | `feat(api): implement GET /insights adherence engine`
  - **Kriter:** V1'in elle hazırladığı test senaryolarının tamamı hesaplama motorunda doğru sonuç veriyor.
- **B1-4 · Backend Hata Düzeltmeleri ve Kararlılık**
  - **İş:** Staging testlerinde tespit edilen mantık ve filtreleme hatalarını gider.
  - **Tarih:** 20 Ekim → 25 Ekim | **Bağımlılık:** V1-5
  - **Dosyalar:** `backend/app/api/`
  - **Branch / PR:** `b1/fix-api-issues` | `fix(api): resolve plan and insights calculation bugs`
  - **Kriter:** Açık API issue'ları kapatıldı.
- **B1-5 · `POST /plans/{id}/reschedule` Uç Noktası (P1 - MVP Onaylı)**
  - **İş:** Hamza'nın nihai onayıyla MVP kapsamında uygulanır (`api-contract.md:259-273`):
    - Gövdeden `new_start` (zorunlu), `new_end` (isteğe bağlı), `reason` (isteğe bağlı), `source` (isteğe bağlı) al.
    - Planın kimliği doğrulanmış kullanıcıya ait olduğunu doğrula; ait değilse K-1 uyarınca `404 not_found` dön.
    - `public.plans` tablosunda `planned_start = new_start`, `planned_end = new_end` değerlerini güncelle.
    - **Orijinal Zamanın ve Denetim İznin Korunması:** `outcomes` tablosunda ayrı bir `original_start` sütunu bulunmadığından, orijinal plan zamanını `note` alanında (`"Rescheduled from <old_start>..<old_end>. Reason: <reason>"`) açıkça sakla. `outcomes` satırını `status = 'postponed'`, `postponed_to = new_start`, `reported_via = 'web'` ile oluştur. Böylece sözleşme satır 261'deki "orijinal zaman, denetim kaydı ve sonuç olayları üzerinden korunur" şartı mevcut şema değiştirilmeden tam olarak sağlanır.
    - Güncellenmiş Plan nesnesini 200 OK ile dön.
  - **Hedef Tarih:** 17 Ekim → 18 Ekim | **Bağımlılık:** B3-1
  - **Dosyalar:** `backend/app/api/plans.py`, `backend/tests/test_plans.py`
  - **Branch / PR:** `b1/plan-reschedule` | `feat(api): implement POST /plans/{id}/reschedule endpoint`
  - **Kriter:** Plan zamanı güncellendi, outcomes tablosuna eski zamanı içeren postponement eklendi, yetkisiz erişimde 404 döndü, testler yeşil.

---

### B4 — Ahmet Zeren (Backend Sonuç Bildirimi)
*(Not: Ahmet aynı zamanda D1 donanım sorumlusudur; backend iş yükü tek odak noktasına indirilmiştir).*

- **B4-1 · `POST /plans/{id}/outcome` Uç Noktası (P0)**
  - **İş:** Plana sonuç kaydet (`status`: done/postponed/skipped; `reported_via`: web/device/auto).
    - Plan kullanıcıya ait değilse K-1 uyarınca `404 not_found` dön.
    - Var olan sonuç güncellenmez; her kayıt yeni bir immutable olaydır.
  - **Tarih:** 14 Ekim → 16 Ekim | **Bağımlılık:** B3-1, K-1
  - **Dosyalar:** `backend/app/api/outcomes.py` (yeni), `backend/app/main.py`, `backend/tests/test_outcomes.py` (yeni)
  - **Branch / PR:** `b4/plan-outcome` | `feat(api): implement POST /plans/{id}/outcome`
  - **Kriter:** 201 Created yanıtı, 401 unauthorized, yabancı plana 404 yanıtı ve trigger immutability testleri yeşil.
- **B4-2 · Cihaz–Backend Entegrasyon Doğrulaması**
  - **İş:** ESP32'den staging backend'e gönderilen outcome kayıtlarının veritabanına ve web listesine anlık yansıdığını doğrula.
  - **Tarih:** 20 Ekim → 22 Ekim | **Bağımlılık:** E-5, D1-2
  - **Dosyalar:** `esp32/README.md`
  - **Branch / PR:** `b4/docs/device-integration` | `docs(esp32): verify device API communication`
  - **Kriter:** Buton basışından sonra web listesinde ilgili planın durumu güncellendi.

---

### B2 — Ülkü Sena (Nemotron & AI Plan Çıkarımı)

- **B2-1 · Nebius Token Factory LLM İstemcisi (P0)**
  - **İş:** Nebius Token Factory üzerinden NVIDIA Nemotron'u JSON modunda çağıran HTTP istemcisini yaz. Zaman aşımı (timeout) ve hata yakalama ekle.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** E-3, K-6
  - **Dosyalar:** `backend/app/ai/llm.py` (yeni), `backend/app/config.py`, `.env.example`, `backend/tests/test_llm.py` (yeni)
  - **Branch / PR:** `b2/nebius-llm-client` | `feat(ai): add Nebius Token Factory LLM client`
  - **Kriter:** Mock HTTP testleri geçiyor; canlı denemede geçerli JSON dönüyor.
- **B2-2 · `POST /parse` Uç Noktası (P0)**
  - **İş:** Doğal dildeki metni `ai/schema.json` ile kısıtlanmış `ParsedPlan` nesnesine çevir.
    - Bearer token zorunludur.
    - Model çıktısını doğrula; geçersizse 1 kez tekrar dene, yine olmazsa `502 parse_failed` dön. Sağlayıcı hatasında `503 llm_unavailable` dön.
    - Veritabanına yazmaz. B5'in de kullanabilmesi için `parse_text(...)` fonksiyonunu dışa aç.
  - **Tarih:** 15 Ekim → 17 Ekim | **Bağımlılık:** B2-1
  - **Dosyalar:** `backend/app/api/parse.py` (yeni), `ai/prompts/parse_plan.md` (yeni), `backend/app/main.py`, `backend/tests/test_parse.py` (yeni)
  - **Branch / PR:** `b2/parse-endpoint` | `feat(api): implement POST /parse with Nemotron`
  - **Kriter:** `create_plan`, `clarify`, `unsupported`, 422 ve 502/503 test senaryoları yeşil.
- **B2-3 · Prompt İyileştirme ve Doğruluk Ölçümü**
  - **İş:** V1'in hazırladığı test setini çalıştıran değerlendirme scripti yaz; prompt'u optimize et.
  - **Tarih:** 18 Ekim → 23 Ekim | **Bağımlılık:** V1-2, B2-2
  - **Dosyalar:** `ai/eval/run_eval.py` (yeni), `ai/prompts/parse_plan.md`
  - **Branch / PR:** `b2/prompt-eval` | `test(ai): evaluate and tune Nemotron parse prompt`
  - **Kriter:** En az %85 intent ve tarih çıkarma doğruluğu sağlandı.
- **B2-4 · `GET /plans/{id}/suggestion` Öneri ve Hava Durumu Uç Noktası (P1 - MVP Onaylı)**
  - **İş:** Hamza'nın nihai onayıyla MVP kapsamında uygulanır (D-009 ve `api-contract.md:213-242`):
    - Planın kullanıcıya ait olduğunu doğrula (değilse `404 not_found`).
    - B3-7 store metoduyla plan için kayıtlı öneri olup olmadığını kontrol et; kayıtlı öneri varsa doğrudan bu öneriyi dön.
    - Kayıtlı öneri yoksa: Minimal çalışan hava durumu kontrolünü (ör. Open-Meteo ücretsiz API veya mocklanabilir hava durumu servisi) ve geçmiş uyum verisini kontrol et.
    - Koşullar uygunsa (ör. hava durumu yağışlı/uygunsuz veya geçmiş uyum düşüklüğü): Sözleşmeye uygun öneri üret (`plan_id`, `reason`: "weather"|"pattern", `message`, `proposed_start`, `proposed_end`, `evidence`: { `forecast`, `adherence_pct` }), B3-7 ile DB'ye kaydet ve dön.
    - Koşullar oluşmazsa veya yeterli veri yoksa: Sözleşme uyarınca `{"suggestion": null}` dön.
    - **Önemli Kural (`suggestion: null` Kısıtı):** `{"suggestion": null}` yanıtı yalnızca sözleşmede belgelenmiş durumlarda (yetersiz veri veya erteleme gerektirmeyen elverişli hava koşulları) geçerli bir yanıttır; onaylanan MVP öneri akışını uygulamak yerine bir kestirme veya ikame olarak ASLA kullanılamaz.
    - Sonraki tüm isteklerde kaydedilmiş öneri döndürülür (MVP kapsamında otomatik güncelleme yapılmaz).
    - **Teknik Engel ve Geri Çekilme (Fallback) Kuralı:** Dış hava durumu servisinde kesinti/rate-limit vb. teknik engel yaşanırsa, engel açıkça belgelenir ve sistem sessizce kaldırılmak yerine güvenli fallback (`null` veya kural bazlı öneri) ile çalışmaya devam eder; özellik sessizce silinmez.
  - **Hedef Tarih:** 18 Ekim → 19 Ekim | **Bağımlılık:** B3-1, B3-7
  - **Dosyalar:** `backend/app/api/suggestions.py` (yeni), `backend/app/services/weather.py` (yeni), `backend/app/main.py`, `backend/tests/test_suggestions.py` (yeni)
  - **Branch / PR:** `b2/suggestion-endpoint` | `feat(api): implement GET /plans/{id}/suggestion with weather check`
  - **Kriter:** İlk istekte hava durumuna göre öneri üretilip kaydediliyor; ikinci istekte kayıtlı öneri dönüyor; uygunsuz koşulda null dönüyor; testler yeşil.

---

### B5 — Burak Varol (Whisper STT Entegrasyonu)

- **B5-1 · Groq Whisper STT İstemcisi (P1)**
  - **İş:** Mono 16 kHz WAV ses dosyasını Groq Whisper Large V3 ile metne dönüştüren istemciyi yaz.
  - **Hedef Tarih:** 14 Ekim → 16 Ekim | **Bağımlılık:** E-3 (B2-1 merge edilince config'e ekle)
  - **Dosyalar:** `backend/app/ai/stt.py` (yeni), `backend/app/config.py`, `backend/tests/test_stt.py` (yeni)
  - **Branch / PR:** `b5/whisper-client` | `feat(ai): add Groq Whisper speech-to-text client`
  - **Kriter:** Mock testler ve örnek ses transkripsiyonu başarılı.
- **B5-2 · `POST /voice` Uç Noktası (P1)**
  - **İş:** `multipart/form-data` ile gelen mono 16 kHz WAV ses dosyasını al (en fazla 10 sn / 320 KB; fazlasına `413 payload_too_large`). Sesi metne çevirip B2'nin `parse_text` fonksiyonuna ilet. Niyet `create_plan` ise planı `source: "voice"` ile kaydet ve planı dön (K-3).
  - **Hedef Tarih:** 17 Ekim → 18 Ekim | **Bağımlılık:** B5-1, B2-2, K-3
  - **Dosyalar:** `backend/app/api/voice.py` (yeni), `backend/pyproject.toml` (`python-multipart`), `backend/app/main.py`, `backend/tests/test_voice.py` (yeni)
  - **Branch / PR:** `b5/voice-endpoint` | `feat(api): implement POST /voice endpoint`
  - **Kriter:** Geçerli sesle 201 Created + Plan dönüyor; clarify ve boyut aşımı durumları test edildi.
- **B5-3 · Ses ve API Hata Düzeltmeleri**
  - **İş:** ESP32 kayıtlarıyla yapılan testlerde tespit edilen transkripsiyon ve timeout hatalarını düzelt.
  - **Tarih:** 20 Ekim → 25 Ekim | **Bağımlılık:** D2-2, V1-6
  - **Dosyalar:** `backend/app/api/voice.py`, `backend/app/ai/stt.py`
  - **Branch / PR:** `b5/fix-voice-issues` | `fix(voice): handle audio conversion and timeout edge cases`
  - **Kriter:** Cihazdan gelen kayıtlar sorunsuz metne dönüşüyor.

---

### W1 — Taylan (Web Plan Oluşturma & Liste Akışı)

- **W1-1 · React + Vite Proje İskeleti ve API İstemcisi (P0)**
  - **İş:** `web/` içinde React + Vite + TypeScript projesi başlat. Bearer token yönetimi, `?t=` URL parametresi yakalama (`history.replaceState` ile temizleme) ve `POST /demo/session` ile demo butonu ekle.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** Yok (W2 bu iskeleti bekler)
  - **Dosyalar:** `web/` (yeni proje dosyaları), `.github/workflows/web-build.yml` (yeni)
  - **Branch / PR:** `w1/react-skeleton` | `feat(web): initialize React app and auth API client`
  - **Kriter:** `npm run build` CI'da başarıyla tamamlanıyor; "Try Demo" butonu yerel backend'den token alıyor.
- **W1-2 · Metinle Plan Oluşturma Akışı (P0)**
  - **İş:** Metin kutusu -> `POST /parse` -> onay ekranı -> `POST /plans` (UUID `Idempotency-Key` ile) akışını kur. Clarify yanıtında soru kutusunu göster; unsupported durumunda uyarı ver.
  - **Tarih:** 16 Ekim → 17 Ekim | **Bağımlılık:** B2-2 (hazır olana kadar mock veri ile)
  - **Dosyalar:** `web/src/pages/CreatePlan.*`, `web/src/api/`
  - **Branch / PR:** `w1/create-plan-flow` | `feat(web): add natural language plan creation page`
  - **Kriter:** Metin yazıldığında plan oluşuyor, onaylanınca backend'e kaydediliyor.
- **W1-3 · Plan Listesi ve Sonuç Bildirme Ekranı (P0)**
  - **İş:** `GET /plans` ile kullanıcının planlarını listele. Her planda **Done / Postponed / Skipped** butonları sun. Butona basılınca `POST /plans/{id}/outcome` (`reported_via: "web"`) çağır ve listeyi güncelle.
  - **Tarih:** 17 Ekim → 18 Ekim | **Bağımlılık:** B1-1, B4-1
  - **Dosyalar:** `web/src/pages/PlanList.*`, `web/src/components/`
  - **Branch / PR:** `w1/plan-list-outcomes` | `feat(web): add plan listing and outcome reporting`
  - **Kriter:** Planlar listeleniyor; sonuca basınca backend'de satır oluşup ekranda güncelleniyor.
- **W1-4 · Web Entegrasyon Hata Giderme**
  - **İş:** Staging API ile yapılan testlerdeki state ve form hatalarını gider.
  - **Tarih:** 20 Ekim → 24 Ekim | **Bağımlılık:** E-5, V1-5
  - **Dosyalar:** `web/src/`
  - **Branch / PR:** `w1/fix-web-integration` | `fix(web): resolve plan creation and listing bugs`
  - **Kriter:** Açık web issue'ları kapatıldı.

---

### W2 — Sevde Betül (Web Tasarım, Analiz Ekranı & Dağıtım)

- **W2-1 · Tasarım Dili ve Ortak UI Bileşenleri (P0)**
  - **İş:** Renk paleti, tipografi ve ortak bileşenleri (Button, Card, Modal, Input, Badge, Toast) Vanilla CSS / modüler CSS ile kur.
  - **Tarih:** 14 Ekim → 16 Ekim | **Bağımlılık:** W1-1 (iskelet merge edildikten sonra entegre et)
  - **Dosyalar:** `web/src/styles/`, `web/src/components/ui/`
  - **Branch / PR:** `w2/design-system` | `feat(web): establish design tokens and shared UI components`
  - **Kriter:** W1'in ekranları bu bileşenleri kullanarak derlenebiliyor.
- **W2-2 · Analiz (Insights) Ekranı (P1)**
  - **İş:** `GET /insights` yanıtını görselleştir: Uyum yüzdesi (% adherence), gün/saat dağılımı, ertelenen hedefler. Periyot seçimi (`week`, `last_week`, `all`). Veri yoksa "Not enough data" mesajı ver. `data_label: "demo"` ise "Sample Data" rozeti koy.
  - **Hedef Tarih:** 17 Ekim → 19 Ekim | **Bağımlılık:** B1-3 (hazır olana kadar mock veri ile)
  - **Dosyalar:** `web/src/pages/Insights.*`, `web/src/components/`
  - **Branch / PR:** `w2/insights-screen` | `feat(web): implement insights analytics dashboard`
  - **Kriter:** Demo verisiyle grafikler ve yüzdeler doğru çiziliyor.
- **W2-3 · Netlify Canlı Dağıtımı**
  - **İş:** `web/netlify.toml` yapılandırmasını yap; siteyi Netlify üzerinde HTTPS ile yayınla; staging API URL'ini ortam değişkenine bağla.
  - **Tarih:** 20 Ekim → 22 Ekim | **Bağımlılık:** E-5
  - **Dosyalar:** `web/netlify.toml` (yeni), `web/README.md`
  - **Branch / PR:** `w2/netlify-deploy` | `chore(web): configure Netlify continuous deployment`
  - **Kriter:** Canlı Netlify URL'i üzerinden tüm web demo akışı hatasız çalışıyor.
- **W2-4 · Mobil Uyumluluk, Yükleme ve Boş Durumlar**
  - **İş:** 375 px mobil ekran genişliğinde responsive görünümü düzelt; Skeleton/Loading, Empty State ve Error State ekranlarını tamamla. Tüm metinlerin İngilizce olduğunu doğrula.
  - **Tarih:** 22 Ekim → 25 Ekim | **Bağımlılık:** W1-3, W2-2
  - **Dosyalar:** `web/src/`
  - **Branch / PR:** `w2/responsive-states` | `fix(web): refine responsive layout, empty and error states`
  - **Kriter:** Mobilde kayma yok; API kapalıyken kullanıcı dostu hata ekranı çıkıyor.
- **W2-5 · Web Demo Ekran Kayıtları**
  - **İş:** Canlı arayüzden metinle plan ekleme, sonuç bildirme ve analiz ekranının temiz ekran kayıtlarını alıp video teslim sorumluları Hamza ve Ahmet'e ilet.
  - **Tarih:** 27 Ekim → 27 Ekim | **Bağımlılık:** E-8
  - **Dosyalar:** Repo dışı (video klipleri)
  - **Kriter:** Klipler video sorumlularına (Hamza ve Ahmet) ulaştırıldı.

---

### D1 — Ahmet Zeren (ESP32 Donanım, Butonlar ve Ekran)

- **D1-1 · Firmware İskeleti, Wi-Fi ve HTTPS Bağlantısı (P1)**
  - **İş:** `esp32/` klasörüne temiz firmware projesini yükle (PlatformIO / Arduino). Wi-Fi ve HTTPS ile backend `GET /health` isteğini doğrula. Hassas anahtarları `secrets.h`'a al ve `.gitignore`'a ekle; repoya yalnızca `secrets.example.h` koy.
  - **Hedef Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** Yok (D2 bu iskeleti bekler)
  - **Dosyalar:** `esp32/` (yeni dosyalar), `esp32/README.md`, `.gitignore`
  - **Branch / PR:** `d1/firmware-skeleton` | `feat(esp32): add firmware skeleton with Wi-Fi and HTTPS`
  - **Kriter:** Seri monitörde Wi-Fi IP'si ve HTTP 200 health yanıtı görüldü.
- **D1-2 · Butonlarla Sonuç Bildirimi (P1)**
  - **İş:** `GET /me/upcoming` ile sıradaki planı al. Buton basışlarını dinle:
    - Kısa basış: `done`
    - Çift basış: `postponed`
    - Uzun basış: `skipped`
    Sonucu `POST /plans/{id}/outcome` (`reported_via: "device"`) ile ilet.
  - **Hedef Tarih:** 16 Ekim → 18 Ekim | **Bağımlılık:** B1-2, B4-1, B3-3
  - **Dosyalar:** `esp32/src/buttons.*`, `esp32/src/api.*`
  - **Branch / PR:** `d1/outcome-buttons` | `feat(esp32): report plan outcomes via hardware buttons`
  - **Kriter:** Butona basıldığında backend'de ilgili sonuç kaydı oluştu.
- **D1-3 · Ekran Durum Bilgilendirmesi (P1)**
  - **İş:** OLED / LCD ekranda sıradaki plan başlığı, kalan süre, kayıt durumu ve Wi-Fi bağlantı ikonunu göster.
  - **Hedef Tarih:** 18 Ekim → 19 Ekim | **Bağımlılık:** D1-2
  - **Dosyalar:** `esp32/src/display.*`
  - **Branch / PR:** `d1/display-status` | `feat(esp32): display upcoming plan and device status`
  - **Kriter:** Sıradaki plan ekranda okunabilir şekilde gösteriliyor.
- **D1-4 · Yeniden Bağlanma, Devre Montajı ve Kasa**
  - **İş:** Wi-Fi kopmalarında otomatik yeniden bağlanma döngüsünü tamamla. Devreyi perfboard üzerine lehimle; kablolamayı ve kutu montajını bitir. Bağlantı şemasını repoya ekle.
  - **Tarih:** 20 Ekim → 25 Ekim | **Bağımlılık:** D1-2
  - **Dosyalar:** `esp32/`, `esp32/README.md`, `esp32/docs/schematic.png`
  - **Branch / PR:** `d1/hardware-packaging` | `fix(esp32): add auto-reconnect and document hardware schematic`
  - **Kriter:** Cihaz kutulanmış ve demo masasında kablosuz çalışır durumda.
- **D1-5 · Donanım Video Çekimi ve Demo Video Ortak Teslimi (Ahmet Zeren & Hamza Yüksel)**
  - **İş:** Çalışan ESP32 cihazının, OLED ekranının, buton basışlarının ve kutulanmış donanımın en az 1 dakikalık net videosunu çek. Hamza ile birlikte demo video kurgusunu, seslendirmesini ve senaryosunu ortaklaşa koordine et (Hamza E-10 ile ortak teslim).
  - **Tarih:** 27 Ekim → 28 Ekim | **Bağımlılık:** D1-4, K-9
  - **Dosyalar:** Repo dışı (video klibi)
  - **Kriter:** Donanım çekimleri tamamlandı; Hamza ile video kurgu ve teslim koordinasyonu sağlandı.

---

### D2 — Eren (I2S Mikrofon ve Ses Yükleme)

- **D2-1 · I2S Mikrofon WAV Kayıt Modülü (P1)**
  - **İş:** INMP441 mikrofonu ile mono, 16 kHz, 16-bit PCM formatında en fazla 10 saniye (en fazla 320 KB) ses kaydeden modülü yaz. WAV header'ını doğru oluştur.
  - **Hedef Tarih:** 14 Ekim → 16 Ekim | **Bağımlılık:** D1-1 (iskelet merge edilince)
  - **Dosyalar:** `esp32/src/audio_record.*`
  - **Branch / PR:** `d2/i2s-recording` | `feat(esp32): record 16kHz mono WAV audio via I2S`
  - **Kriter:** Kaydedilen WAV bilgisayarda temiz dinlenebiliyor; boyutu 320 KB altında.
- **D2-2 · Sesi `POST /voice` Uç Noktasına Yükleme (P1)**
  - **İş:** Kaydedilen sesi HTTPS üzerinden `multipart/form-data` ile `POST /voice` endpoint'ine gönder. Dönen JSON'daki transkripti ekrana yazdırılmak üzere D1'in ekran modülüne ilet.
  - **Hedef Tarih:** 17 Ekim → 19 Ekim | **Bağımlılık:** B5-2, B3-3, D1-3
  - **Dosyalar:** `esp32/src/audio_upload.*`, `esp32/src/main.*`
  - **Branch / PR:** `d2/voice-upload` | `feat(esp32): upload audio recordings to POST /voice`
  - **Kriter:** Cihaza konuşulduğunda backend'de plan oluşuyor ve ekranda transkript görünüyor.
- **D2-3 · Mikrofon Kazancı ve Gürültü Ayarları**
  - **İş:** V1 ile birlikte ortam gürültüsü ve farklı mesafelerden ses kayıt kalitesini optimize et; mikrofon kazanç (gain) parametresini ayarla.
  - **Tarih:** 20 Ekim → 24 Ekim | **Bağımlılık:** D2-2, V1-6
  - **Dosyalar:** `esp32/src/audio_record.*`
  - **Branch / PR:** `d2/audio-tuning` | `fix(esp32): tune microphone gain and buffer stability`
  - **Kriter:** Gürültülü ortamda transkripsiyon başarısı doğrulandı.

---

### V1 — Mustafa Kerem (Veri Setleri, Kalite Güvence ve Test)

- **V1-1 · Demo Tohum Veri Seti (P0 - Kritik)**
  - **İş:** 3–4 haftalık geçmiş plan ve sonuç verisi oluştur (`demo/seed/demo_plans.json`). İki profil içersin: düzenli kullanıcı ve erteleyen kullanıcı. Tarihler "günden geriye doğru" dinamik hesaplanabilir yapıda olsun.
  - **Tarih:** 14 Ekim → 15 Ekim | **Bağımlılık:** Yok (B3-4 bu veriyi bekler!)
  - **Dosyalar:** `demo/seed/demo_plans.json` (yeni), `demo/seed/README.md` (yeni)
  - **Branch / PR:** `v1/demo-seed-data` | `test(data): provide synthetic 4-week demo dataset`
  - **Kriter:** B3 veriyi format hatası olmadan oturuma yükleyebildi.
- **V1-2 · AI Değerlendirme Veri Seti (P0)**
  - **İş:** En az 50 Türkçe ve İngilizce örnek cümle içeren test seti hazırla (`parse_cases.jsonl`). Göreli tarihler ("yarın 18:00"), belirsiz ifadeler (`clarify`), desteklenmeyen cümleler (`unsupported`) ve anlamsız metinler içersin.
  - **Tarih:** 14 Ekim → 16 Ekim | **Bağımlılık:** Yok (B2-3 bu veriyi bekler!)
  - **Dosyalar:** `ai/eval/parse_cases.jsonl` (yeni)
  - **Branch / PR:** `v1/parse-test-cases` | `test(ai): create evaluation dataset for plan parsing`
  - **Kriter:** Dosya JSONL formatında geçerli ve B2'ye teslim edildi.
- **V1-3 · Insights İçin Beklenen Sonuç Doğrulama Tablosu (P0)**
  - **İş:** Elle hesaplanmış 5-8 senaryoluk test fixture'ı hazırla (hiç sonuç yokken `null`, birden fazla sonuçta sonuncunun alınması, unreported planların paydadan çıkarılması vb.).
  - **Tarih:** 16 Ekim → 17 Ekim | **Bağımlılık:** Yok (B1-3 bu veriyi bekler!)
  - **Dosyalar:** `backend/tests/fixtures/insights_cases.json` (yeni)
  - **Branch / PR:** `v1/insights-fixtures` | `test(insights): add verified calculation fixtures`
  - **Kriter:** B1 testlerinde bu fixture'ları başarıyla kullandı.
- **V1-4 · AI Doğruluk Raporu**
  - **İş:** B2'nin eval scriptini çalıştır; intent, tarih ve kategori çıkarma doğruluk oranlarını rapora dök.
  - **Tarih:** 20 Ekim → 23 Ekim | **Bağımlılık:** B2-3
  - **Dosyalar:** `ai/eval/REPORT.md` (yeni)
  - **Branch / PR:** `v1/ai-accuracy-report` | `docs(ai): document Nemotron parsing accuracy report`
  - **Kriter:** Rapor README'ye eklenebilir şekilde hazırlandı.
- **V1-5 · Uçtan Uca Test Planı ve Issue Takibi**
  - **İş:** Staging ve Netlify üzerinde Gate 1 akışını, sınır durumları ve güvenlik kontrollerini test et. Tespit edilen hataları GitHub Issues üzerinde ilgili kişiye ata.
  - **Tarih:** 20 Ekim → 25 Ekim | **Bağımlılık:** E-5, W2-3
  - **Dosyalar:** `docs/TEST_PLAN.md` (yeni)
  - **Branch / PR:** `v1/test-plan` | `docs: add end-to-end QA test plan and tracking`
  - **Kriter:** Tüm akış maddeleri test edildi, bloklayıcı issue kalmadı.
- **V1-6 · Ses Tanıma Kalite Karşılaştırması**
  - **İş:** ESP32 kaydı ile Whisper transkripsiyon başarısını farklı gürültü ortamlarında test et ve raporla.
  - **Tarih:** 22 Ekim → 24 Ekim | **Bağımlılık:** D2-2, B5-2
  - **Dosyalar:** `docs/TEST_PLAN.md` (ses bölümü)
  - **Branch / PR:** `v1/voice-qa-report` | `docs: record speech recognition evaluation results`
  - **Kriter:** Ses test sonuçları dokümante edildi.
- **V1-7 · Son Sürüm Regresyon Testi**
  - **İş:** `v1.0.0` release freeze sürümünde baştan sona tüm demo adımlarını son kez doğrula.
  - **Tarih:** 26 Ekim → 26 Ekim | **Bağımlılık:** E-9
  - **Dosyalar:** `docs/TEST_PLAN.md`
  - **Branch / PR:** `v1/final-regression` | `docs: record final release regression test sign-off`
  - **Kriter:** Kritik hata yok onayı verildi.

---

## 4. Gün Gün Teslimat Çizelgesi

*(Not: P0 görevleri kesin taahhüttür; P1 görevlerine ait tarihler 19 Ekim dondurması öncesi hedeflenen çalışma tarihleridir, kesin teslimat taahhüdü değildir).*

```
14 Eki (Çar): E-1, E-2, D-011 Kararları, B3/B1/B4 metot mutabakatı, Bölüm 1.1 yerel .env kurulumu
15 Eki (Per): B3-1 (DB Adaptörü - Kritik!), B3-2, B2-1, W1-1, D1-1, V1-1, E-3 (Test kimlik bilgileri doğrulaması)
16 Eki (Cum): B4-1 (Outcome API), B1-2 (Upcoming API), B3-3 (Token Script), B5-1, W2-1, D2-1, V1-2, E-4 (Dockerfile)
17 Eki (Cts): B2-2 (Parse API), B3-4 (Demo Seed), B1-5 (Reschedule - MVP Onaylı), W1-2, V1-3
18 Eki (Paz): B5-2 (Voice API), W1-3, D1-2, E-5 (Staging Deploy) -> GATE 1 İLK UÇTAN UCA TEST
19 Eki (Pzt): B1-3 (Insights API), B3-5, B2-4 (Suggestion & Hava Durumu - MVP Onaylı), B3-7 (Öneri DB Saklama), W2-2, D1-3, D2-2, E-6 -> FEATURE FREEZE (v0.9.0)
----------------------------------------------------------------------------------------------------------------------
20–22 Eki:   E-7, B4-2, W2-3 (Netlify), E-8 Canlı ortam geçişi
23 Eki (Per): B2-3, V1-4 (AI Doğruluk Raporu)
24 Eki (Cum): W1-4, D2-3, V1-6 (Ses Test Raporu)
25 Eki (Cts): B1-4, B3-6, B5-3 (STT İnce Ayar), W2-4, D1-4, V1-5 (QA Tamamlama)
26 Eki (Paz): E-9 (İngilizce README), V1-7 -> RELEASE FREEZE (v1.0.0)
27 Eki (Sal): W2-5 (Web kayıtları), D1-5 (Donanım çekimleri) -> Hamza & Ahmet koordinasyonunda
28 Eki (Çar): E-10 / D1-5 (Demo Video YouTube'da yayında — Hamza Yüksel & Ahmet Zeren ortak)
29 Eki (Per): E-11 -> DEVPOST BAŞVURUSU (Resmi hedef gün!)
30 Eki (Cum): Son yedek kontrol (20:00 TR saati resmi kapanış)
```

---

## 5. Sözleşme Uyumu ve Kapsam Yönetimi

29 Ekim teslimatını korumak için sözleşme ve kararlar belgesinde yer alan tüm uç noktaların durumu aşağıda açıkça listelenmiştir. Hiçbir özellik sessizce silinmemiş, olası çelişkiler tanımlanmıştır:

| Özellik / Uç Nokta | Sözleşme / Karar Dayanağı | Durum ve Uygulama Planı | Sözleşme / Karar Çelişki Notu |
|---|---|---|---|
| **Gate 1 Çekirdeği** (`/parse`, `/plans`, `/outcome`, `/insights`) | `api-contract.md`, `D-004`, `D-006`, `D-010` | **P0 (Mutlak Öncelik):** 19 Ekim dondurmasına kadar eksiksiz teslim edilir. | Çelişki yok. |
| **Öneri / Suggestions** (`GET /plans/{id}/suggestion`) | `api-contract.md:213-242`, `D-009` | **P1 (MVP Kapsamında Onaylandı - Hamza):** Minimal sözleşme uyumlu akış uygulanır (B2-4, B3-7). İlk çağrıda hava durumu (Open-Meteo) ve geçmiş veriye bakılarak öneri üretilir ve DB'ye kaydedilir. Sonraki çağrılarda kayıtlı öneri döner. | Çelişki giderildi. `{"suggestion": null}` yalnızca belgelenmiş alan koşullarında (yetersiz veri, elverişli hava koşulları) geçerlidir; onaylanan MVP öneri akışını uygulamak yerine bir ikame olarak kullanılamaz. Teknik engel durumunda belgelenir ve fallback sunulur. |
| **Yeniden Planlama** (`POST /plans/{id}/reschedule`) | `api-contract.md:259-273` | **P1 (MVP Kapsamında Onaylandı - Hamza):** Minimal sözleşme uyumlu sürüm uygulanır (B1-5). `plans` tablosunda `planned_start`/`planned_end` güncellenirken, `outcomes` tablosuna `status: 'postponed'`, `postponed_to: new_start`, `note: "Rescheduled from <old_start>..<old_end>. Reason: <reason>"`, `reported_via: 'web'` kaydı eklenir. | Çelişki yok. `outcomes` tablosunda `original_start` sütunu bulunmadığından, önceki zaman `note` alanında saklanarak ve ilk oluşturma zamanı `plan_creation_requests.response_snapshot` içinde tutularak denetim izi sıfır şema değişikliğiyle korunur. |
| **Yaklaşan Planlar** (`GET /me/upcoming`) | `api-contract.md:325-340` | **P1 (Pull-based):** 15 dk ofset ve 24 sa pencere önerilen işletimsel varsayılanlarıyla uygulanır (B1-2, D1-2). | Çelişki yok (varsayılanlar teklif olarak korunur). |
| **Demo Videosu Teslimi** | `TASKS.md`, `D-011` | **Ortak Sahiplik (Hamza Yüksel & Ahmet Zeren):** Ahmet donanım çekimlerini yapar, Hamza YouTube ve Devpost teslimini yürütür; kurgu ve seslendirme ortak koordine edilir (E-10, D1-5). Burak Varol (B5) yalnızca Whisper STT'ye odaklanır. | Çelişki giderildi. Video yalnızca gerçek çalışan sistemi yansıtır. |
| **Ortak Test Kimlik Bilgileri & Yerel Ortam** | `D-011`, Bölüm 1.1 | **Uygulandı:** Hamza test anahtarlarını temin etti. `SUPABASE_SERVICE_KEY` asla tüm ekibe (Web/Donanıma) verilmez; rol bazlı en az ayrıcalık (least privilege) uygulanır. Tüm ekip yerel `.env` kurar ve yerel duman testlerini çalıştırır. Sırlar repoya girmez. | Yerel ortam ile canlı staging sunucu kurulumu birbirinden ayrılmıştır. |
| **Otomatik Zamanlayıcı (Cron Daemon)** | `D-007`, `D-009` | **P2 (Ertelendi):** Hackathon için pull-based `/me/upcoming` yeterlidir. Ayrı bir Nebius cron job API sunucusundan bağımsız zamanlayıcı MVP dışına ertelenmiştir. | D-007 ve D-009 zamanlayıcı hedefiyle çelişir; README'de "pull-based yaklaşım kullanılmıştır" diye belgelenecektir. |
| **Web Ses Girişi** | `api-contract.md:158`, `D-009` | **P2 (Ertelendi):** Web'de metin girişi P0'dır. Tarayıcı içi WAV mikrofon kaydı P2 olarak tutulur. | Çelişki yok (metin girişi sözleşmeyle uyumludur). |
| **Veri İhraç / İmha** (`/me/export`, `/me/data`) | `api-contract.md:342-361` | **P2 (Dondurma Sonrası):** Hackathon jüri demosu için kritik değildir; 19 Ekim sonrasına bırakılmıştır. | Sözleşme uç noktasıdır; MVP demo akışını etkilemez. |
| **Android / Capacitor Uygulaması** | `D-009`, `TASKS.md:100` | **P2 (İptal):** Web uygulamasının mobil tarayıcı uyumluluğu (W2-4) tek başına yeterlidir; yerel paketleme yapılmayacaktır. | D-009 bir proje hedefi olarak anar; iptal edilerek web responsive tutulmuştur. |

---

## 6. Ek: Teknik Notlar ve Standartlar

- **Ortak Hata Formatı**:
  ```json
  { "error": "validation_error", "message": "İstek alanları geçersiz." }
  ```
  Hata kodları: `unauthorized` (401), `forbidden` (403), `not_found` (404), `payload_too_large` (413), `validation_error` (422), `parse_failed` (502), `llm_unavailable` (503).
- **Kimlik Doğrulama**: `Authorization: Bearer <raw_token>`
- **Plan Idempotency**: `Idempotency-Key: <UUID>`
- **Saat Formatı**: Saat dilimi içeren ISO 8601 (`YYYY-MM-DDTHH:MM:SS+03:00`).
- **Veritabanı İmmutability Kuralı**: `outcomes` tablosu salt-eklenir (append-only) yapıdadır; `UPDATE` tetikleyici ile engellenir, her durum bildirimi yeni bir satırdır.
