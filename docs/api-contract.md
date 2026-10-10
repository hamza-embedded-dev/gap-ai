# GAP API Sözleşmesi v1

Bu belge Backend, AI, Web ve ESP32 arasındaki ortak arayüz sözleşmesidir. İstek ve yanıt biçimleri için `ai/schema.json` ile birlikte tek doğruluk kaynağıdır. Mock sunucu da aynı endpoint'leri, istek ve yanıt biçimlerini ve hata kodlarını uygulamalıdır.

Bu belge veya `ai/schema.json` değişirse değişiklik PR ile incelenmelidir. Entegratör ve kod inceleyicisi onaylamadan istemciler yeni endpoint ya da alan varsaymamalıdır.

## Genel kurallar

- HTTPS kullanılır. Aksi belirtilmedikçe istek ve yanıtlar UTF-8 kodlu JSON'dur.
- Zaman damgaları saat dilimi içeren ISO 8601 biçimindedir. Örnek: `2026-10-06T18:00:00+03:00`.
- Kimlikler sıralı olmayan UUID değerleridir.
- Yinelenen plan oluşturma isteklerini önlemek için isteğe bağlı `Idempotency-Key` başlığı kullanılabilir.

### Hata biçimi

```json
{
  "error": "validation_error",
  "message": "İstek alanları geçersiz."
}
```

| Kod | HTTP | Açıklama |
|---|---:|---|
| `unauthorized` | 401 | Token eksik veya geçersiz |
| `forbidden` | 403 | Kaynak başka bir kullanıcıya ait |
| `not_found` | 404 | Kaynak bu kullanıcı için bulunamadı |
| `payload_too_large` | 413 | Ses veya istek gövdesi boyut sınırını aşıyor |
| `validation_error` | 422 | İstek, sözleşmeye veya `ai/schema.json` dosyasına uymuyor |
| `rate_limited` | 429 | İstek sınırı aşıldı |
| `parse_failed` | 502 | Model çıktısı yeniden denemeden sonra da doğrulanamadı |
| `llm_unavailable` | 503 | Model sağlayıcısına ulaşılamıyor |

## Kimlik doğrulama

- Kimlik doğrulaması gereken isteklerde `Authorization: Bearer <token>` kullanılır.
- Tokenlar uzun ve tahmin edilemez olmalıdır. Veritabanında yalnızca token özeti (hash) saklanır. Ham tokenlar loglanmaz.
- İlk giriş bağlantısındaki `?t=<token>` değeri web istemcisi tarafından bir kez okunur ve `history.replaceState` ile adres çubuğundan kaldırılır. Sonraki isteklerde Bearer başlığı kullanılır. Token tek kullanımlık değildir; iptal edilene kadar geçerlidir.
- Demo erişimi ayrıdır: `POST /demo/session`, izole ve geçici bir demo kullanıcısı için token döndürür.
- Her sorgu, kimliği doğrulanmış kullanıcının verileriyle sınırlandırılır. Yetkilendirme backend tarafından yapılır.

## Ortak nesneler

`ParsedPlan`, `ai/schema.json` dosyasında tanımlıdır.

### Plan

```json
{
  "id": "uuid",
  "title": "Koşu",
  "category": "sport",
  "planned_start": "2026-10-06T18:00:00+03:00",
  "planned_end": "2026-10-06T19:00:00+03:00",
  "recurrence_rule": null,
  "source": "text",
  "created_at": "2026-10-05T21:10:00+03:00",
  "latest_outcome": null
}
```

`source`: `text` | `voice` | `device`.

### Sonuç olayı

Bir plan için birden fazla sonuç olayı kaydedilebilir.

```json
{
  "id": "uuid",
  "plan_id": "uuid",
  "status": "postponed",
  "actual_start": null,
  "postponed_to": "2026-10-08T19:00:00+03:00",
  "note": null,
  "reported_via": "web",
  "reported_at": "2026-10-06T17:00:00+03:00"
}
```

`status`: `done` | `postponed` | `skipped`.  
`reported_via`: `web` | `device` | `auto`.

### Öneri

```json
{
  "plan_id": "uuid",
  "reason": "weather",
  "message": "Yağmur bekleniyor. Perşembe 19.00 uygun görünüyor. Ertelemek ister misin?",
  "proposed_start": "2026-10-08T19:00:00+03:00",
  "proposed_end": "2026-10-08T20:00:00+03:00",
  "evidence": {
    "forecast": "rain",
    "adherence_pct": 66.7
  }
}
```

`reason`: `weather` | `pattern`. Öneriler veritabanına kaydedilir ve ilgili planla ilişkilendirilir. Mesajı model oluşturur; sayılar ve uygun zaman aralıkları backend tarafından hesaplanır. Hava durumu öneri üretiminde kullanılır.

## Endpoint'ler

### `GET /health`

Kimlik doğrulaması gerekmez.

Yanıt:

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### `POST /demo/session`

Kimlik doğrulaması gerekmez. Demo verileriyle izole bir demo kullanıcısı oluşturur. Oturum süresi 24 saattir.

Yanıt:

```json
{
  "token": "<raw token>",
  "expires_at": "2026-10-07T11:00:00+03:00",
  "is_demo": true
}
```

### `GET /me`

Giriş yapan kullanıcının profilini döndürür.

Yanıt:

```json
{
  "id": "uuid",
  "display_name": "Ada",
  "timezone": "Europe/Istanbul",
  "is_demo": false
}
```

### `PATCH /me`

Profil bilgilerini günceller.

İstek:

```json
{
  "display_name": "Ada",
  "timezone": "Europe/Istanbul"
}
```

Her iki alan da isteğe bağlıdır. Yanıt güncellenmiş profildir.

### `POST /parse`

Doğal dildeki metni doğrulanmış bir `ParsedPlan` nesnesine dönüştürür. Veritabanına yazmaz. Web akışında plan, kullanıcı onayından sonra `POST /plans` ile kaydedilir.

İstek:

```json
{
  "text": "Yarın 18'de koşuya çıkacağım.",
  "language": "tr",
  "current_date": "2026-10-05",
  "timezone": "Europe/Istanbul"
}
```

`language` isteğe bağlıdır. Web'deki ses girdisinin transkripti de metin olarak bu endpoint'e gönderilebilir.

Yanıt, `ai/schema.json` dosyasındaki `ParsedPlan` biçimindedir. `intent` değeri `clarify` ise istemci `clarification_question` alanını gösterir ve plan oluşturmaz.

### `POST /voice`

Kimlik doğrulaması gerekir. ESP32 ses akışını işler.

İstek `multipart/form-data` biçimindedir: `audio`, isteğe bağlı `language`, `current_date` ve `timezone`.

Ses biçimi mono PCM/WAV, 16 kHz, 16-bit olmalı ve en fazla 10 saniye (yaklaşık 320 KB) sürmelidir.

Ses metne çevrilir ve sonuç `ai/schema.json` dosyasına göre doğrulanır. `intent` değeri `create_plan` ise backend planı kaydeder. Yanıtta metinsel sonuç zorunludur; TTS/sesli yanıt zorunlu değildir.

Plan oluşturulduğunda yanıt, transkriptin ve `ParsedPlan` sonucunun yanında kaydedilmiş planı da içerir:

```json
{
  "transcript": "Yarın 18'de koşuya çıkacağım.",
  "parsed_plan": {
    "...": "ai/schema.json ile uyumlu create_plan sonucu"
  },
  "plan": {
    "...": "oluşturulan Plan"
  }
}
```

`intent` değeri `clarify` veya `unsupported` ise plan kaydedilmez; yanıt transkript ve `ParsedPlan` içerir.

### `POST /plans`

Doğrulanmış ve kullanıcı tarafından onaylanmış bir planı kaydeder. Backend `planned_start` ve `planned_end` değerlerini `date`, `time`, `duration_minutes` (varsayılan 60 dakika) ve kullanıcının saat diliminden oluşturur.

İstek:

```json
{
  "parsed_plan": {
    "...": "intent değeri create_plan olan ParsedPlan"
  },
  "source": "text"
}
```

Yanıt oluşturulan `Plan` nesnesidir (`201 Created`). `intent` değeri `create_plan` dışında olan istekler `422 validation_error` ile reddedilir.

### `GET /plans`

Yalnızca giriş yapan kullanıcının planlarını döndürür. İsteğe bağlı sorgu parametreleri: `from`, `to`.

Yanıt:

```json
{
  "items": [
    "...Plan nesneleri"
  ]
}
```

### `GET /plans/{id}/suggestion`

Hava durumu ve geçmiş verilere dayalı öneriyi oluşturur, veritabanına kaydeder ve döndürür. Hava durumu entegrasyonu MVP kapsamındadır.

Yanıt:

```json
{
  "suggestion": null
}
```

veya:

```json
{
  "suggestion": {
    "...": "Suggestion nesnesi"
  }
}
```

### `POST /plans/{id}/outcome`

Bir plan için sonuç olayı kaydeder.

İstek:

```json
{
  "status": "done",
  "actual_start": "2026-10-06T18:17:00+03:00",
  "postponed_to": null,
  "note": null,
  "reported_via": "web"
}
```

Yanıt oluşturulan sonuç olayıdır (`201 Created`). Cihazlar `postponed_to` olmadan `postponed` gönderebilir; analiz bunu hedef zamanı bilinmeyen erteleme olarak sayar.

### `POST /plans/{id}/reschedule`

Kullanıcının onayından sonra yeni plan zamanını uygular. Orijinal zaman, denetim kaydı ve sonuç olayları üzerinden korunur.

İstek:

```json
{
  "new_start": "2026-10-08T19:00:00+03:00",
  "new_end": "2026-10-08T20:00:00+03:00",
  "reason": "Hava durumu nedeniyle ertelendi.",
  "source": "weather_suggestion"
}
```

`new_end` isteğe bağlıdır. `source`: `user` | `weather_suggestion` | `pattern_suggestion`. Yanıt güncellenmiş `Plan` nesnesidir.

### `GET /insights`

Backend tarafından hesaplanan deterministik istatistikleri döndürür. Sorgu parametresi: `period` = `week` (varsayılan) | `last_week` | `all`.

Yanıt:

```json
{
  "period": "week",
  "planned": 4,
  "done": 2,
  "postponed": 1,
  "skipped": 0,
  "unreported": 1,
  "adherence_pct": 66.7,
  "avg_start_delay_min": 17,
  "by_weekday": {
    "Tuesday": {
      "planned": 2,
      "done": 1,
      "postponed": 1
    }
  },
  "by_hour": {
    "18": {
      "planned": 3,
      "done": 2
    }
  },
  "by_category": {
    "sport": {
      "planned": 3,
      "done": 2
    }
  },
  "postponed_targets": [
    {
      "weekday": "Thursday",
      "hour": 19,
      "count": 1
    }
  ],
  "trend_vs_prev": {
    "adherence_pct_delta": 12.5
  },
  "narrative": "Raporlanan üç planın ikisini tamamladın...",
  "is_demo": false,
  "data_label": "real"
}
```

`adherence_pct`, bitiş zamanı geçmiş ve sonucu bildirilmiş planlarda `done / (done + postponed + skipped)` oranıdır. Sonucu olmayan geçmiş planlar `unreported` sayılır ve paydadan çıkarılır. Planın son sonuç olayı uyum hesabında kullanılır; tüm `postponed` olayları örüntü analizine dahil edilir. `narrative` boş veya `null` olabilir. `data_label`: `real` | `demo`.

### `GET /me/upcoming`

Hatırlatma ve cihaz katmanları için yaklaşan planları döndürür. İsteğe bağlı sorgu parametreleri: `since`, `to`.

Yanıt:

```json
{
  "items": [
    {
      "plan_id": "uuid",
      "title": "Koşu",
      "planned_start": "2026-10-06T18:00:00+03:00",
      "reminder_at": "2026-10-06T17:45:00+03:00"
    }
  ]
}
```

### `GET /me/export`

Yalnızca giriş yapan kullanıcının profilini, planlarını, sonuçlarını, kayıtlı önerilerini ve önbelleğe alınmış analizlerini dışa aktarır. Ham tokenlar dışa aktarıma dahil edilmez.

### `DELETE /me/data`

`X-Confirm-Delete: true` başlığını gerektirir.

Kullanıcıya ait planları, sonuçları, kayıtlı önerileri, önbelleğe alınmış analizleri ve ilgili anıları siler. Denetim kaydı yalnızca silme işleminin gerçekleştiğini tutar; silinen içeriği tutmaz.

Yanıt:

```json
{
  "deleted": true,
  "counts": {
    "plans": 12,
    "outcomes": 15,
    "suggestions": 4
  }
}
```

## Entegrasyon kuralı

Hiç kimse bu sözleşmede tanımlanmamış endpoint veya payload uydurmamalıdır. Bu dosyadaki veya `ai/schema.json` dosyasındaki değişiklikler entegratör ve kod inceleyicisi tarafından incelenen PR ile yapılmalıdır.
