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
