# Kararlar

Kararların ve gerekçelerinin kısa kaydı. En yeni karar en altta yer alır.

## D-001 (2026-10-06) Yetkilendirme backend tarafından yapılır

Supabase Auth yerine özel token kullanılır. Backend kullanıcıyı token üzerinden bulur ve tüm veritabanı sorgularını o kullanıcının verileriyle sınırlar. Row Level Security (RLS), yalnızca gerçekten yapılandırılıp test edildiyse README'de etkin olarak belirtilir.

## D-002 (2026-10-06) Erişim tokenları

Veritabanında tokenın kendisi değil, yalnızca özeti (hash) saklanır. `?t=` bağlantısındaki token istemci tarafından bir kez okunur ve adres çubuğundan kaldırılır; sonraki isteklerde Bearer başlığı kullanılır. Token tek kullanımlık değildir ve iptal edilene kadar geçerlidir.

## D-003 (2026-10-06) İzole demo oturumları

`POST /demo/session`, demo verileriyle geçici ve izole bir demo kullanıcısı oluşturur. Oturum 24 saat geçerlidir. Jüri üyeleri birbirlerinin verilerini göremez. Demo verileri her zaman örnek veri olarak işaretlenir.

## D-004 (2026-10-06) Tek AI şeması

AI çıktısının tek şeması `ai/schema.json` dosyasıdır. Desteklenen niyetler `create_plan`, `clarify` ve `unsupported` değerleridir. Belirsiz isteklerde tahmin yürütmek yerine `clarify` sonucu ve bir açıklama sorusu döndürülür.

## D-005 (2026-10-06) Sonuç geçmişi

Bir plan için birden fazla sonuç olayı kaydedilebilir. Cihazlar `postponed_to` alanını göndermeyebileceği için bu alan isteğe bağlıdır. Böylece erteleme örüntüleri analiz edilebilir.

## D-006 (2026-10-06) Planın zamanlara dönüştürülmesi

Backend, `ParsedPlan`, kullanıcının saat dilimi ve `duration_minutes` değerini kullanarak `planned_start` ve `planned_end` alanlarını oluşturur. Süre belirtilmezse varsayılan süre 60 dakikadır.

## D-007 (2026-10-06) Nebius Serverless

Hatırlatma zamanlayıcısının Nebius Serverless Job olarak çalıştırılması hedeflenir. Bu mümkün olmazsa zamanlayıcı backend sunucusuyla çalıştırılır ve bu durum README'de doğru şekilde belgelenir. Nebius Token Factory çağrısı platform kullanım gereksinimini karşılar.

## D-008 (2026-10-06) Dahili planlama belgeleri

Ayrıntılı dahili plan ve görev panosu Türkçe tutulur ve herkese açık depoda yer almaz. Herkese açık depo yalnızca İngilizce teslim belgelerini içerir. Etkinlik kredi kodları hiçbir zaman depoya eklenmez.

## D-009 (2026-10-10) Uygulama kararları

- Web uygulaması React ile geliştirilir
- Firmware için mevcut `esp32/` klasörü korunur.
- Ses biçimi mono PCM/WAV, 16 kHz, 16-bit olur ve kayıt en fazla 10 saniye sürer.
- ESP32 akışında kimliği doğrulanmış `POST /voice` isteği sesi yazıya çevirir, planı oluşturur ve doğrular, ardından planı kaydeder. Yanıtta metin bulunması zorunludur; sesli yanıt isteğe bağlıdır.
- Web akışında `POST /parse` metni veya ses kaydının yazıya çevrilmiş halini işler. Kullanıcı planı onayladıktan sonra `POST /plans` planı kaydeder.
- Öneriler veritabanına kaydedilir ve ilgili kullanıcı ile planla ilişkilendirilir.
- Hava durumu entegrasyonu MVP kapsamındadır ve öneri üretiminde kullanılır.
- Zamanlayıcı ayrı bir zamanlanmış görev olarak çalışır; API sunucusunun sürekli açık olduğu varsayılmaz.
- Ortak API hata kodları: `413 payload_too_large`, `422 validation_error`, `502 parse_failed` ve `503 llm_unavailable`.

D-009 kararlarıyla çelişen API sözleşmesi, AI şeması, veritabanı şeması ve mimari belgeler güncellenmelidir.

## D-010 (2026-10-12) Gate 1 kimlik doğrulama ve saat dilimi davranışı

- `POST /parse` geçerli bir Bearer token gerektirir; backend D-001 uyarınca kullanıcıyı token üzerinden belirler.
- Tarih ve saat yorumlamasında kimliği doğrulanmış kullanıcının kayıtlı saat dilimi tek otoritedir. İstek `timezone` alanı içeriyorsa kayıtlı saat dilimiyle aynı olmalıdır; farklıysa mevcut `422 validation_error` döndürülür. Alan yoksa kayıtlı saat dilimi kullanılır.
- `POST /plans`, D-006 uyarınca `planned_start` ve `planned_end` değerlerini kullanıcının kayıtlı saat diliminden türetir.
- D-003 kapsamındaki demo kullanıcısının varsayılan saat dilimi `Europe/Istanbul`'dur.
- `GET /insights`, uygun ve sonuç bildirilmiş plan yoksa `adherence_pct` için `null` döndürür.

## D-011 (2026-10-13) Gate 1 Açık Konuların Çözümü ve Nihai Kapsam Kararları

### A. Onaylanmış Mimari ve Kapsam Kararları (Confirmed Decisions)

- **K-1 (Yabancı Plan Erişimi):** Kimliği doğrulanmış kullanıcıya ait olmayan bir `plan_id` ile yapılan işlemlerde (ör. `/outcome`, `/reschedule`), başka kullanıcıların plan varlığını ifşa etmemek (ID enumeration engellemek) için `404 not_found` ("Kaynak bulunamadı") döndürülür. Bu davranış D-001 ve `docs/api-contract.md` satır 24 tanımıyla tam uyumludur.
- **K-2 (Token Temin Mimarisi):** Donanım (ESP32) ve test kullanıcıları için halka açık kayıt uç noktası açılmaz; token temini idari script (`backend/scripts/create_access_token.py`) ile sağlanacaktır. **Bu script henüz repoda mevcut değildir; B3-3 görevi kapsamında geliştirilip test edilecektir.** Ham token ekrana bir kez yazılır; veritabanında yalnızca SHA-256 + pepper hash saklanır (D-002).
- **K-3 (Ses Kaynaklı Planlar):** `POST /voice` üzerinden oluşturulan planların `source` alanı (ESP32 kaynaklı olanlar dahil) girdi modalitesini yansıtacak şekilde `"voice"` olarak kaydedilir (`20261013_001_gate1_core.sql` check constraint'i ile uyumlu).
- **K-5 (Öneri / Suggestions — MVP İçin Onaylandı):** Hamza'nın nihai kararıyla öneri sistemi MVP kapsamına alınmıştır. Özellik ertelenmeyecek veya sadece `suggestion: null` döndürülecek şekilde kapsam dışı bırakılmayacaktır. D-009 ve `docs/api-contract.md:213-242` davranışına sadık kalınır:
  - İlk uygun istekte hava durumu (minimal hava durumu kontrolü/Open-Meteo) ve geçmiş veriye bakılarak bir öneri üretilir ve veritabanına kaydedilir.
  - Sonraki isteklerde kaydedilmiş öneri döndürülür (MVP kapsamında otomatik güncelleme yapılmaz).
  - `{"suggestion": null}` dönüşü **yalnızca sözleşmede belgelenmiş alan koşullarında** (yetersiz veri, geçmiş uyumsuzluğu olmaması veya hava koşullarının elverişli olması nedeniyle erteleme gerekmemesi) geçerli bir yanıttır; bu durum, onaylanan MVP öneri akışını uygulamak yerine bir ikame, kestirme veya kapsam azaltma olarak ASLA kullanılamaz.
  - Görev sahipleri (B2-4, B3-7), bağımlılıklar, testler ve süreler (19 Ekim Feature Freeze hedefi) kesinleştirilmiştir. Teknik bir engel (ör. dış hava durumu servisinin çökmesi/rate limit) oluşursa engel belgelenir ve geri çekilme (fallback) sunulur; özellik sessizce silinmez.
- **Reschedule (`POST /plans/{id}/reschedule` — Kapsamda Korundu):** Hamza'nın kararıyla bu uç nokta planlanan MVP kapsamında tutulmuştur. Sözleşmeyi (`api-contract.md:259-273`) ve mevcut migration şemasını değiştirmeden en küçük uyumlu sürüm uygulanır:
  - **Şema Analizi ve Orijinal Zamanın Korunması:** Mevcut `public.outcomes` tablosunda `postponed_to` (yeni hedef zaman) alanı bulunurken, orijinal plan zamanı için ayrı bir `original_start` sütunu yer almamaktadır. `plans` tablosundaki `planned_start` / `planned_end` güncellendiğinde önceki zamanın kaybolmaması için, en güvenli ve sıfır şema değişikliği gerektiren çözüm: `POST /plans/{id}/reschedule` çağrısında `outcomes` tablosuna eklenen `postponed` olayının `note` alanında orijinal plan zamanının (`"Rescheduled from <old_start>..<old_end>. Reason: <reason>"`) açıkça saklanmasıdır (ayrıca ilk plan oluşturma zamanı `plan_creation_requests.response_snapshot` içinde de korunmaktadır). Böylece denetim izi kuralı mevcut veri modeliyle eksiksiz sağlanır (B1-5).
- **K-6 (Ortak Test Kimlik Bilgileri ve Rol Bazlı Erişim):** Hamza ekibin test ortamı için gereken API anahtarlarını temin etmiştir. Güvenlik ve en az ayrıcalık (least privilege) kuralı uyarınca:
  - **Ayrıcalıklı Sunucu Sırrı (Server-Only Secret):** `SUPABASE_SERVICE_KEY` RLS korumalarını atlayan tam yetkili bir anahtardır; **ASLA tüm ekibe (özellikle Web ve Donanım üyelerine) dağıtılmaz.** Yalnızca DB adaptörünü geliştiren ve migration uygulayan B3 (Ece Ulvi) ile sunucu dağıtımını yapan E (Hamza Yüksel) tarafından backend `.env` dosyasında kullanılır.
  - **Rol Bazlı Sır Ayrımı:** Web geliştiricileri (W1, W2) doğrudan veritabanı veya model anahtarı almaz; yalnızca istemci yapılandırmasını (backend API URL'i) kullanır. Donanım ekibi (D1, D2) veritabanı veya LLM anahtarlarına erişmez; yalnızca yerel Wi-Fi bilgileri ve provizyon edilmiş cihaz Bearer token'ını `secrets.h` içinde tutar. B2 yalnızca Nebius, B5 yalnızca Groq anahtarını alır.
  - Tüm üyeler `.env.example` dosyasından kendi yerel `.env` dosyalarını oluşturacak, yalnızca rollerine özel onaylanmış anahtarları yapılandıracak ve yerel duman testini çalıştıracaktır.
  - `.env`, `secrets.h`, API anahtarları, service-role anahtarları ve sırlar ASLA git'e commit edilmeyecek; GitHub issue, PR, kaynak kod veya ortak belgelere yapıştırılmayacaktır.
  - Yerel test ortamı ile merkezi staging sunucu dağıtımı birbirinden açıkça ayrılmıştır. Canlı staging barındırma sağlayıcısı ve URL detayları dağıtım aşamasında (E-5) kesinleşecektir.
- **K-7 (Ses Sözleşmesi ve Web Önceliği):** Ses sözleşmesi mono PCM/WAV, 16 kHz, 16-bit, <=10 sn (`MAX_AUDIO_SECONDS=10`) olarak ortaktır. Web uygulamasında metin tabanlı giriş (`POST /parse`) P0 birincil akıştır; tarayıcı içi ses kaydı web teslimini riske atmamak adına P2 opsiyonel eklentidir.
- **K-8 (İstatistik Saat Dilimi ve Hafta Sınırı):** `GET /insights` hesaplamalarında kullanıcının kayıtlı IANA saat dilimi tek otoritedir (D-010). Hafta sınırı ISO 8601 standardına uygun olarak Pazartesi 00:00:00 başlar ve Pazar 23:59:59 biter.
- **K-9 (Demo Videosu Nihai Sahipliği):** Demo videosu tesliminin ortak sahipliği Hamza Yüksel ve Ahmet Zeren'e aittir. Burak Varol (B5) video teslimi sorumluluğundan çıkarılmış ve tamamen Whisper STT entegrasyonuna odaklanmıştır.
  - Ahmet Zeren (D1): Çalışan donanım/ESP32 çekimleri ve cihaz gösterim senaryolarından sorumludur.
  - Hamza Yüksel (E): Nihai YouTube yüklemesi, Devpost teslimi ve genel koordinasyondan sorumludur.
  - Seslendirme (narration), kurgu (editing) ve senaryo bölünmesi: Henüz kesin bir alt kırılım yapılmadığından aralarındaki ortak koordinasyona bırakılmıştır; üzerinde anlaşılmamış bir ayrım uydurulmaz.
  - Video yalnızca gerçek çalışan arayüz ve donanımı gösterir; telifli materyal içermez.
- **K-10 (Eski Belge Ayrımı):** `database/api-docs/` altındaki belgeler geçmiş tasarım referansıdır; projenin tek bağlayıcı sözleşmeleri `docs/api-contract.md` ve `ai/schema.json`'dır. Sözleşmede yer almayan `POST /device/telemetry` gibi uç noktalar uygulanmaz.

### B. Önerilen İşletimsel Varsayılanlar (Proposed Operational Defaults)

- **K-4 (Hatırlatma Ofseti ve Varsayılan Pencere):** `docs/api-contract.md:325-340` metninde bağlayıcı bir kural normatif olarak tanımlanmamış, yalnızca örnek JSON içinde 15 dakikalık fark (`planned_start` 18:00, `reminder_at` 17:45) yer almıştır. Yetkili sözleşmede aksi açıkça belirtilmediği sürece `reminder_at = planned_start - 15 dakika` kuralı ve parametre verilmediğinde `since = now()`, `to = now() + 24 saat` varsayılan aralığı **önerilen işletimsel varsayılan (proposed operational default)** olarak korunmaktadır. Henüz resmi bağlayıcı sözleşme metnine işlenmemiş olup backend (B1-2) ve cihaz (D1-2) implementasyonunda bu varsayılanlar kullanılır. Otomatik push mekanizması bulunmamaktadır, pull-based model geçerlidir.


