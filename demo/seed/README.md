# GAP-AI Demo Tohum Veri Seti (Demo Seed Dataset)

Bu dizin, GAP-AI projesinin izole demo oturumları (`POST /demo/session`) ve jüri/geliştirici testleri için hazırlanmış 4 haftalık sentetik demo geçmiş verisini içerir.

---

## 1. Bu Veri Seti Ne İçin Var?

GAP-AI sisteminde yeni bir demo oturumu açıldığında (`POST /demo/session`, D-003), kullanıcının ekranında (`GET /plans`), istatistik sayfasında (`GET /insights`) ve öneri motorunda (`GET /plans/{id}/suggestion`) anlamlı, dolu ve test edilebilir bir deneyim sunulabilmesi için geçmiş plan ve sonuç olaylarına ihtiyaç duyulur.

Bu veri seti:
- Sistemin soğuk başlangıç (cold-start) sorununu çözer.
- Deterministik GAP analizini (`GET /insights`), uyum yüzdelerini (`adherence_pct`), ortalama başlama gecikmelerini (`avg_start_delay_min`) ve erteleme örüntülerini (`postponed_targets`) doğrulamayı sağlar.
- B3 (Ece Ulvi) tarafından geliştirilecek demo oturumu tohumlama mekanizmasına (`B3-4`) doğrudan girdi sağlar.

---

## 2. Kullanıcı Profilleri

Veri seti iki farklı gerçekçi davranış profilini temsil eder:

### A. Düzenli Kullanıcı (`regular`)
- **Tanım:** Planlarına yüksek oranda sadık, disiplinli ve tutarlı bir kullanıcı profili.
- **Plan Sayısı:** 22 plan (20 geçmiş plan, 2 yaklaşan plan).
- **Uyum Oranı (Adherence):** **%90.0** (18 `done`, 1 `postponed`, 1 `skipped`).
- **Başlama Gecikmesi (Avg Start Delay):** Ortalama **~8.1 dakika** (neredeyse tam zamanında başlama).
- **Kategori Dağılımı:** `sport`, `work`, `study`, `meeting`, `health`, `social`, `personal`.
- **Raporlama Kanalları:** `web` ve `device` (fiziksel donanım/ESP32 buton bildirimleri simülasyonu).

### B. Erteleyen Kullanıcı (`procrastinator`)
- **Tanım:** Planları sık sık erteleyen, geciktiren veya atlayan, belirgin erteleme örüntülerine sahip profil.
- **Plan Sayısı:** 24 plan (22 geçmiş plan, 2 yaklaşan plan).
- **Uyum Oranı (Adherence):** **%50.0** (10 `done`, 5 `postponed`, 5 `skipped`, 2 `unreported`).
- **Başlama Gecikmesi (Avg Start Delay):** Yüksek gecikmeler (özellikle ertelenen günlere taşınan görevlerde 24–48 saatlik gecikmeler; aynı gün başlayanlarda 30–50 dakika).
- **Erteleme Örüntüsü (Pattern Pool):** Geçmişte toplam **14 adet** `postponed` olayı bulunmaktadır. Özellikle Salı günleri planlanan koşu ve çalışma aktivitelerinin tekrarlı olarak **Perşembe 19:00**'a ertelenmesi örüntüsü işlenmiştir. Bu örüntü, GAP-AI öneri motorunun (`reason: "pattern"`) test edilmesi için tasarlanmıştır.
- **Bildirilmeyen Planlar (Unreported):** Sonucu girilmemiş 2 adet geçmiş plan içerir (`docs/api-contract.md:323` uyarınca paydadan çıkarılma kuralını test eder).

---

## 3. Zaman Kapsamı ve Tarih Tasarımı

- **Zaman Aralığı:** Yaklaşık 4 hafta (29 gün: 17 Eylül 2026 – 16 Ekim 2026).
- **Referans Tarih (Anchor Date):** `2026-10-15` (Proje takvimi referansı). Dosyanın kök seviyesindeki `anchor_date` alanı bu referansı belirtir.
- **Saat Dilimi:** `Europe/Istanbul` (ISO 8601 ofseti: `+03:00`), D-010 ve `docs/api-contract.md:36` ile tam uyumlu.
- **Yaklaşan Planlar (Upcoming):** Oturum açıldığı an `GET /me/upcoming` uç noktasının boş kalmaması için her iki profilde de bugüne (Gün 0) ve yarına (Gün +1) ait planlar eklenmiştir.

### Statik Depolama ve Dinamik Tarih Ayrımı

> [!IMPORTANT]
> **Statik JSON vs. Çalışma Zamanı (Runtime) Ayrımı:**
> `demo_plans.json` saf bir JSON veri dosyasıdır; kendi başına kod çalıştıramaz. Bu nedenle dosya içerisinde tarihler, `anchor_date: "2026-10-15"` referans alınarak önceden hesaplanmış geçerli ISO 8601 string'leri olarak saklanmaktadır.
> 
> Backend modellerinde `extra="forbid"` kuralı uygulandığından ve PostgREST tablo şemasında bulunmayan sütunlar kabul edilmediğinden, plan nesnelerinin içine `day_offset` gibi schema dışı alanlar **bilerek eklenmemiştir**.

### B3 İçin Dinamik Tarih Uyarlama Rehberi (B3-4 Bağımlılığı)
`POST /demo/session` çağrıldığında tarihlerin oturumun açıldığı günden ("bugünden") geriye doğru 4 haftalık olarak veritabanına yazılması, **B3-4 görevi kapsamında B3 loader'ının çalışma zamanında yapacağı bir tarih kaydırmasıyla** sağlanacaktır:

```python
# B3-4 loader'ı için önerilen dinamik tarih kaydırma örneği:
from datetime import datetime, timezone

# 1. Oturum açılma anı ile seed referans tarihi arasındaki fark hesaplanır
anchor_dt = datetime.fromisoformat(seed["anchor_date"] + "T12:00:00+03:00")
delta = datetime.now(timezone.utc) - anchor_dt

# 2. İlgili tarihler bu delta kadar kaydırılarak veritabanına yazılır
def shift(iso_str: str | None) -> str | None:
    if not iso_str:
        return None
    return (datetime.fromisoformat(iso_str) + delta).isoformat()

# Örnek:
# shifted_start = shift(plan["planned_start"])
# shifted_end = shift(plan["planned_end"])
```

Böylece `demo_plans.json` hiçbir şema ihlali yapmadan saf ve doğrulanabilir kalırken, B3-4 oturum oluşturma anında veriyi dinamik olarak "bugün" merkezli kaydedebilir.

---

## 4. Veri Modeli ve Sözleşme Uyumu

Veri setindeki her alan, projenin bağlayıcı sözleşmelerine harfiyen uymaktadır:

- **Kaynak Dokümanlar:**
  - `docs/api-contract.md` (Plan, Outcome ve Insights sözleşmesi)
  - `database/migrations/20261013_001_gate1_core.sql` (Veritabanı şeması ve kısıtları)
  - `ai/schema.json` (Kategori ve geçerli değerler)
  - `docs/decisions.md` (D-003, D-005, D-010, K-8)

### Plan Alanları (`plans` tablosu / `PlanResponse`)
- `id`: RFC 4122 uyumlu deterministik UUIDv4.
- `title`: Plan başlığı (Türkçe, doğal dilde).
- `category`: `sport`, `study`, `work`, `meeting`, `health`, `social`, `personal`, `other`.
- `planned_start` & `planned_end`: `Europe/Istanbul` saat dilimli ISO 8601 (`planned_end > planned_start`).
- `recurrence_rule`: İsteğe bağlı kural (MVP tohumlarında `null`).
- `source`: `text`, `voice`, `device` (D-011 K-3 uyumlu).
- `created_at`: Plan oluşturulma zaman damgası (`created_at <= planned_start`).

### Sonuç Alanları (`outcomes` tablosu)
- `id`: Benzersiz UUID.
- `plan_id`: İlgili planın `id` değeri (Foreign Key).
- `status`: `done`, `postponed`, `skipped`.
- `actual_start`: Yalnızca `done` durumunda (veya başlama bildirilmişse) geçerli ISO damgası.
- `postponed_to`: Ertelenen hedef tarih/saat veya bilinmiyorsa `null` (D-005).
- `note`: İsteğe bağlı açıklama metni.
- `reported_via`: `web`, `device`, `auto`.
- `reported_at`: Olayın bildirildiği zaman damgası.

---

## 5. Uyum Oranı (Adherence) ve Çoklu Outcome Hesabı

`docs/api-contract.md:323` ve `docs/decisions.md:D-005` gereğince bir plan için birden fazla sonuç olayı bulunabilir (ör. önce ertelenip sonra tamamlanan planlar).

GAP-AI mimarisinde uyum hesabı şu kurallarla yapılır:
1. **Son Olay Kuralı:** Bir planın birden fazla outcome kaydı varsa, `reported_at` zamanına göre **en son eklenen olay** planın nihai durumunu belirler.
2. **Payda Hesabı:** Bitiş zamanı geçmiş ve en az bir sonuç bildirilmiş planlar için:
   $$\text{adherence\_pct} = \frac{\text{done}}{\text{done} + \text{postponed} + \text{skipped}} \times 100$$
3. **Bildirilmeyenler (Unreported):** Geçmişte kalan ancak hiçbir outcome kaydı bulunmayan planlar uyum hesabında **paydadan çıkarılır**.
4. **Örüntü Havuzu:** Nihai durumu `done` olsa bile aradaki tüm `postponed` olayları örüntü analizi havuzunda (`postponed_targets`) saklanır.

---

## 6. Veri Bütünlüğü ve Güvenlik Beyanı

1. **Tamamen Sentetiktir:** Bu veri setinde yer alan tüm isimler, planlar, saatler ve UUID'ler yapay olarak üretilmiştir.
2. **Gerçek Kullanıcı Verisi İçermez:** Hiçbir gerçek kişisel veri, e-posta, kimlik veya production verisi barındırmaz.
3. **Secret / Token İçermez:** Dosyada hiçbir API key, token veya gizli anahtar bulunmaz.

---

## 7. Yerel Doğrulama Komutları

Veri setinin JSON geçerliliğini, Pydantic şema uyumunu ve metriklerini doğrulamak için aşağıdaki komut çalıştırılabilir:

```powershell
python -c "
import json
from datetime import datetime

with open('demo/seed/demo_plans.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for name, prof in data['profiles'].items():
    plans = {p['id']: p for p in prof['plans']}
    outcomes = prof['outcomes']
    print(f'Profil: {name} | Toplam Plan: {len(plans)} | Toplam Outcome: {len(outcomes)}')
"
```
