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


Bu kuralları ekibe WhatsApp’tan veya toplantıda tek tek okumak yerine, "Ekip Anayasası / Proje Kuralları" başlığı altında herkesin ilk bakışta anlayacağı net bir dille şöyle aktarabilirsin:

Ekip Anayasası (Kurallarımız)
1. main Kutsaldır, Doğrudan Dokunmak Yasaktır

Kimse ana koda (main) doğrudan kod gönderemez.

Herkes kendine özel bir çalışma kolu (branch) açacak, işi bitince "Kontrol edip ana koda ekleyin" diye istek (Pull Request) atacak.

2. Kol (Branch) İsimlendirme Formatı

Kafamıza göre dal ismi açmıyoruz. Formatımız: <rol>/<kısa-iş>

Örnekler: Backend 1 için b1/api-skeleton, Web 2 için w2/demo-login, Donanım 1 için d1/audio-upload.

3. Kayıt (Commit) Mesajları Düzenli Olacak

Kayıt atarken asdasd veya düzelttim yazmak yok. Format: tür: kısa açıklama

Kullanılacak türler: feat (yeni özellik), fix (hata çözümü), docs (doküman), test (test kodu), chore (ayar/dosya düzeni).

Örnek: feat: ses yukleme fonksiyonu eklendi

4. Çift Göz Kuralı ("Çalışıyor işte" demek yetmez)

Yazdığın kodu ana koda eklemeden önce ekipten en az bir kişi okuyup onaylayacak.

"Çalıştı ama ben de tam anlamadım nasıl oldu" kabul edilmiyor; yazdığın kodun neden ve nasıl çalıştığını bilmek zorundasın.

5. Kafana Göre Yeni Uç Nokta veya Veri Alanı Uydurmak Yok

Sistemde hangi verinin nereye gideceğinin tek bir patronu var: docs/api-contract.md ve ai/schema.json.

Burada yazmayan yeni bir adres (endpoint) veya veri alanı uyduramazsınız. Değişiklik gerekiyorsa Entegratör ve Kod İnceleyici onay vermelidir.

6. Şifreler ve Gerçek Kişi Verileri GitHub’a Asla Yüklenmez

API anahtarları, şifreler, Wi-Fi bilgileri ve gerçek öğrenci/kullanıcı bilgileri asla koda doğrudan yazılmayacak.

Bunlar sadece bilgisayarındaki gizli .env dosyasında duracak; GitHub’a sadece boş taslak olan .env.example atılacak.

7. Yapay Zekaya (ChatGPT / Claude / Cursor) Gizli Bilgileri Yapıştırmayın

API anahtarlarını, şifreleri veya gerçek kullanıcı verilerini yapay zekaya kopyala-yapıştır yapmayın.

8. Korsan veya Lisansı Belirsiz Şeyler Eklemeyin

Projeye dışarıdan ekleyeceğiniz her kütüphanenin, fontun, ikonun veya internetten alınan kod parçasının açık kaynak lisansına (MIT, Apache vb.) dikkat edin.

9. main Her Zaman Çalışır Durumda Kalacak

Ana kod asla bozuk olamaz; birisi projeyi indirdiğinde tek tıkla hatasız çalışmalıdır.

19 Ekim 2026 Saat Sınırı (Feature Freeze): Bu tarihten sonra yeni özellik eklemek tamamen yasaktır! Sadece hata düzeltme (bug fix), güvenlik açıkları kapatma, test ve dokümantasyon değişiklikleri kabul edilir.
