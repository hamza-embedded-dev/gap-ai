# Katkıda Bulunma Rehberi

Projeye katkı sağlarken süreçlerimizin düzenli ve güvenli ilerlemesi için lütfen aşağıdaki kurallara uyun:

## Dal (Branch) Yönetimi ve Pull Request'ler

* **`main` dalı korumalıdır:** Doğrudan `main` dalına kod göndermeyin (push yapmayın). Kendi işiniz için her zaman yeni bir dal açın ve tamamladığınızda bir **Pull Request (PR)** oluşturun.
* **Dal isimlendirmeleri:** `<rol>/<kısa-konu>` formatında olmalıdır.
* *Örnekler:* `b1/api-skeleton`, `w2/demo-login`, `d1/audio-upload`


## Commit Mesajları

Commit mesajlarınız `tür: kısa açıklama` formatında olmalıdır. Kullanabileceğiniz türler şunlardır:

* `feat`: Yeni bir özellik
* `fix`: Hata (bug) düzeltmesi
* `docs`: Dokümantasyon değişiklikleri
* `test`: Test eklemeleri veya güncellemeleri
* `chore`: Derleme süreçleri, paket güncellemeleri gibi rutin işler

## Kod İnceleme Süreci

* Her Pull Request en az bir kişi tarafından okunur ve incelenir.
* Sadece kodun "çalışıyor" olması yeterli değildir; yazdığınız kodun **neden ve nasıl çalıştığını** tam olarak bilmelisiniz.

## API ve Şemalar

* API veri yapıları (payload) için **tek otorite** `docs/api-contract.md` ve `ai/schema.json` dosyalarıdır.
* Kendi inisiyatifinizle yeni uç noktalar (endpoint) veya veri alanları uydurmayın.
* Bu kaynak dosyalarda bir değişiklik yapılması gerekiyorsa, bu değişikliğin mutlaka **entegratör** ve **kod inceleyicisi (reviewer)** tarafından onaylanması şarttır.

## Güvenlik ve Gizlilik

* API anahtarlarını, token'ları, Wi-Fi şifrelerini veya gerçek katılımcı verilerini **asla** commitlemeyin.
* Hassas ayarlar için git tarafından yoksayılan `.env` dosyasını kullanın ve örnek şablonları `.env.example` dosyasında tutun.
* Gizli anahtarları, şifreleri veya gerçek kullanıcı verilerini ChatGPT vb. **yapay zeka (AI) araçlarına yapıştırmayın**.

## Lisanslar

* Projeye dışarıdan eklediğiniz her kütüphanenin, fontun, ikonun veya kod parçasının (snippet) lisansını mutlaka kontrol edin.

## Sürüm Takvimi

* **`main` dalı her zaman hatasız çalışmalıdır.**
* Özellik dondurma (Feature Freeze) tarihi olan **19 Ekim 2026** sonrasında projeye yeni özellik eklenmeyecektir. Bu tarihten sonra yalnızca hata düzeltmeleri (bug fix), güvenlik yamaları, testler ve dokümantasyon güncellemeleri kabul edilecektir.






# Contributing

- `main` is protected: work on a branch and open a pull request.
- Branch names: `<role>/<short-topic>`, e.g. `b1/api-skeleton`, `w2/demo-login`, `d1/audio-upload`.
- Commit messages: `type: short description` (`feat`, `fix`, `docs`, `test`, `chore`).
- Every pull request is read by at least one other person. "It works" is not enough: know why it works.
- `docs/api-contract.md` and `ai/schema.json` are the only authority for payloads. Do not invent endpoints or fields.
  Changes to them need review from the integrator and the code reviewer.
- Never commit API keys, tokens, Wi-Fi passwords or real participant data. Use `.env` (ignored) and `.env.example`.
- Do not paste secrets or real user data into AI tools.
- Check the license of every library, font, icon or snippet before adding it.
- `main` must always run. After the feature freeze (19 Oct 2026) only bug, security, test and docs changes are accepted.
