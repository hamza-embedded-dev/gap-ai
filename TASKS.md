# GAP: Görev Listesi (TASKS)

Nebius x NVIDIA Global AI Hackathon için ekip görev planı. **Son gönderim: 30 Ekim 2026, 20:00 (Türkiye saati).** Hedef gönderim günü: **29 Ekim**. Demo, jüri dönemi bitene kadar (15 Aralık) ayakta kalmalıdır.


## Takımlar

| Takım | Üyeler | Sorumluluk |
|---|---|---|
| Donanım Ekibi | Ahmet ve Eren | ESP32 cihazı, ses kaydı, butonlar, ekran ve donanım çekimleri |
| Backend ve AI Pilotları | Hamza Fatih, Ülkü Sena, Ece Ulvi, Ahmet Zeren ve Burak Varol | FastAPI, Whisper ve Nemotron entegrasyonu, analiz motoru, Nebius dağıtımı |
| Web UI Ekibi | Sevde Betül ve Taylan | Web uygulaması, tasarım, Capacitor ile mobil uygulama, yayına alma |
| Veri ve Test | Mustafa Kerem | Supabase şeması, demo verisi, testler ve ölçümler |
| Hikaye ve Sunum | Ahmet ve Hamza | Hikaye, demo videosu, Devpost metinleri, görseller |
| Entegrasyon | Hamza Yüksel | Repo, ortak sözleşmeler, uçtan uca test, README ve gönderim |

## Alınacak kararlar (ilk hafta)

| Karar | Sorumlu | Son tarih |
|---|---|---|
| Web arayüz çatısı (React, Svelte, Vue) | Web UI | 8 Eki (toplantıda) |
| Ses biçimi ve en uzun kayıt süresi (WAV 16 kHz, kısa kayıt) | Donanım + Backend | 8 Eki (toplantıda) |
| Buton eşlemesi (kısa, çift, uzun basış) | Donanım + Backend | 8 Eki (toplantıda) |
| Kullanıcı girişi (Supabase Auth, demo hesabı, cihaz tokenı) | Backend + Web UI | 8 Eki (toplantıda) |
| Nebius Token Factory setup | Entegrasyon + Backend | 8 Eki (toplantıda) |
| Supabase setup | Backend | 8 Eki (toplantıda) |

## Zaman Çizelgesi

| Tarih | Kilometre taşı | Çıkış ölçütü |
|---|---|---|
| 8-10 Eki | Temel kurulum | Repo, API sözleşmesi, Supabase şeması hazır; ESP32 Wi-Fi bağlı; ortak kararlar verildi |
| 14 Eki | İlk uçtan uca akış | ESP32 veya web sesi → FastAPI → Whisper → metin döner |
| 20 Eki | Çekirdek özellikler | Akış A ve B tamam: plan kaydı, buton → sonuç → analiz → öneri web'de görünür; Nebius'ta yayında |
| 26 Eki | Kod dondurma | Yeni özellik yok, yalnızca hata düzeltme; testler yeşil; v1.0 etiketi |
| 27-28 Eki | Video ve belgeler | Demo videosu YouTube'da; README ve Devpost metni hazır |
| 29 Eki | Gönderim | Devpost'a gönderildi (yedek gün 30 Eki; son saat 20:00 Türkiye saati) |
| 30 Eki - 15 Ara | Demo canlı kalır | Sunucu ve kredi takibi; jüri erişimi kesintisiz |

## Bağımlılıklar

- Donanım ve Web UI, Backend'in /voice ve /outcome uç noktalarına bağlı. Bu yüzden API sözleşmesi 10 Eki'de kilitlenir.
- Veri ve Test, Backend'in analiz motoruna ve Supabase şemasına bağlı. Şema 10 Eki'de hazır olmalı.
- Hikaye ve Sunum, Donanım ve Web UI'nin çalışan görüntülerine bağlı. Çekimler 27 Eki'den önce bitmeli.
- Entegrasyon, tüm ekiplerin çıktılarını toplar ve denetler.

## 1. Donanım Ekibi

**Üyeler:** Ahmet ve Eren  
**Sorumluluk:** ESP32 cihazı, ses kaydı, butonlar, ekran ve donanım çekimleri

- [ ] ESP32 geliştirme ortamını kur (Arduino IDE veya ESP-IDF); Wi-Fi ve HTTPS bağlantısını test et. **Son tarih: 10 Eki**
- [ ] I2S mikrofonu bağla; 16 kHz WAV kaydı al, kayıt süresini sınırla (ör. en fazla 15 sn). **Son tarih: 11 Eki**
- [ ] Kaydı HTTPS ile FastAPI aracılığı ile ses serverine yolla; yanıtı (başarılı/hata) cihazda göster. **Son tarih: 17 Eki**
- [ ] Üç buton: kısa basış yapıldı, çift basış ertelendi, uzun basış atlandı; POST /plans/{id}/outcome. **Son tarih: 18 Eki**
- [ ] Ekran: sıradaki plan, kayıt durumu, bağlantı durumu. **Son tarih: 22 Eki**
- [ ] Wi-Fi kopması ve gönderim hatasında yeniden bağlanma ve yeniden deneme. **Son tarih: 24 Eki**
- [ ] Devreyi perf board gibi bir karta düzenli bir şekilde kurmak. **Son tarih: 25 Eki**
- [ ] Kutu/kasa ve kablolama; demo masası düzeni. **Son tarih: 25 Eki**
- [ ] Firmware kaynak kodu ve bağlantı şeması repoda; İngilizce kurulum notu. **Son tarih: 26 Eki**
- [ ] Donanım çekimleri: en az 1 dakikalık net ESP32 görüntüsü (çekim planı Burak ile). **Son tarih: 27 Eki**

## 2. Backend ve AI Pilotları

**Üyeler:** Hamza Fatih, Ülkü Sena, Ece Ulvi, Ahmet Zeren ve Burak Varol  
**Sorumluluk:** FastAPI, Whisper ve Nemotron entegrasyonu, analiz motoru, Nebius dağıtımı

- [ ] FastAPI iskeleti, Dockerfile, ortam değişkenleri (.env.example); gizli anahtarlar repoya girmez. **Son tarih: 10 Eki**
- [ ] OpenAPI Nebius: /voice, /parse, /plans, /plans/{id}/outcome ve önerileri okuma, test etme (Entegrasyon ile). **Son tarih: 11 Eki**
- [ ] Nebius Token Factory bağlantısı; Nemotron ile JSON modu. **Son tarih: 15 Eki**
- [ ] Doğrudan Groq üzerinden Whisper Large V3; zaman aşımı ve hata yönetimi. **Son tarih: 17 Eki**
- [ ] Metinden niyet, tarih, saat, kategori, saat dilimi gibi şeyleri Nemotron ile halletme. **Son tarih: 18 Eki**
- [ ] Pydantic ile JSON doğrulaması; çıkan JSON doğru mu değil mi? Değil ise yeniden deneme. **Son tarih: 21 Eki**
- [ ] Supabase bağlantısı; plan ve sonuç kaydı; benzer geçmiş planları çekme (uzun süreli hafıza). **Son tarih: 24 Eki**
- [ ] Öneri prompt'u: sayılar analiz motorundan gelir, model yalnızca yorumlar; önerileri kaydet. **Son tarih: 24 Eki**
- [ ] GAP analiz motoru: uyum yüzdesi, gün/saat bazında erteleme, gecikme süresi, kronik erteleme tespiti (ör. 3 kez). **Son tarih: 25 Eki**
- [ ] Nebius'a dağıtım (Serverless Endpoint); 15 Aralık'a kadar ayakta kalacak kurulum ve maliyet takibi. **Son tarih: 25 Eki**
- [ ] 7/24 zamanlayıcı görev; çift tetiklenmeyi önle (tek kopya veya veritabanı kilidi). **Son tarih: 25 Eki**
- [ ] Her şeyin serverless endpoint ile birlikte sorunsuz çalıştığını test etme ve son dokunuşlar. **Son tarih: 26 Eki**

## 3. Web UI Ekibi

**Üyeler:** Sevde Betül ve Taylan  
**Sorumluluk:** Web uygulaması, tasarım, Capacitor ile mobil uygulama, yayına alma

- [ ] Arayüz çatısını seç (React, Svelte, Vue). **Son tarih: 8 Eki (toplantıda)**
- [ ] Tasarım dili: renkler, tipografi, bileşenler; ana ekranların taslağı ve ilk versiyon. **Son tarih: 11 Eki**
- [ ] Yazılı giriş + sesli kayıt ile uygulama üzerinden plan ekleme → (ses biçimini Backend ile netleştir). **Son tarih: 15 Eki**
- [ ] Plan listesi ve bugün görünümü; yapıldı, ertelendi, atlandı butonları. **Son tarih: 17 Eki**
- [ ] Analiz ekranı: uyum yüzdesi, gün ve saat bazında erteleme grafikleri. **Son tarih: 20 Eki**
- [ ] Öneri kartları (kabul et / reddet) ve proaktif öneri gösterimi. **Son tarih: 21 Eki**
- [ ] Netlify ile Web sürümünü HTTPS ile yayına al (jüri için demo URL); 15 Aralık'a kadar ayakta. **Son tarih: 24 Eki**
- [ ] Capacitor ile Android uygulaması (mikrofon izni dahil); iOS opsiyonel. **Son tarih: 25 Eki**
- [ ] Yükleme, hata ve boş durumlar; mobil uyumluluk; tüm arayüz metinleri İngilizce. **Son tarih: 25 Eki**
- [ ] Netlify ve Supabase'in birlikte çalıştığının doğrulanması ve testler. **Son tarih: 26 Eki**
- [ ] Demo için ekran kayıtları ve görüntüleri (Burak'a teslim). **Son tarih: 27 Eki**

## 4. Veri ve Test

**Üyeler:** Mustafa Kerem  
**Sorumluluk:** Supabase şeması, demo verisi, testler ve ölçümler

- [ ] Sahte demo verisi oluşturma (bozuk veri (dwnadwad), günlük veri gibi (Yarın 8'de koşuya çıkacağım)): 3-4 haftalık geçmiş, farklı kullanıcı davranışları ile veri seti oluşturma (düzenli, kronik erteleyen). **Son tarih: 15 Eki**
- [ ] Proje belirlenene göre model doğru davranıyor mu gibi bir doğruluk raporu. **Son tarih: 25 Eki**
- [ ] Analiz ve testler: uyum yüzdesi, erteleme örüntüsü, sınır durumlar vb. verilerle test edilip kalite kontrol yapılır. **Son tarih: 25 Eki**
- [ ] Ses tanıma testi: farklı kişi, aksan ve gürültü; ESP32 ve tarayıcı kayıt kalitesi karşılaştırması. **Son tarih: 25 Eki**
- [ ] API ve akış testleri; hatalar GitHub Issues'ta takip edilir. **Son tarih: 26 Eki**
- [ ] Son test. **Son tarih: 26 Eki**

## 5. Hikaye ve Sunum

**Üyeler:** Ahmet ve Hamza  
**Sorumluluk:** Hikaye, demo videosu, Devpost metinleri, görseller

- [ ] Hikaye: problem (niyet ile eylem arasındaki boşluk), hedef kullanıcı, etki: Gibi alanlar için proje özeti (README.md için hazırlık) (markdown ile ve İngilizce yazılacak). **Son tarih: 22 Eki**
- [ ] İngilizce projenin mimarisinin diyagramı (diyagramlar *mermaid* ile yapılacak) ve kapak görseli (kapak görseli photoshop ile fiziksel ürünü içerecek ve entegratör ile kararlaştırılarak yapılacak). **Son tarih: 25 Eki**
- [ ] Devpost proje açıklaması (İngilizce): ne, neden, nasıl ve mermaid diyagramlar ile birleştirilip en son README.md dosyası oluşturulup githuba eklenecek. **Son tarih: 26 Eki**
- [ ] Video çekimi: hedef cihazda çalışan ürün + en az 1 dk donanım; telifli müzik ve üçüncü taraf marka yok. **Son tarih: 27 Eki**
- [ ] Kurgu ve YouTube'a herkese açık yükleme. **Son tarih: 28 Eki**

## 6. Entegrasyon

**Üyeler:** Hamza Yüksel  
**Sorumluluk:** Repo, ortak sözleşmeler, uçtan uca test, README ve gönderim

- [ ] Monorepo yapısı (/backend, /web, /firmware, /docs), branch ve PR kuralları. **Son tarih: 8 Eki (toplantıda)**
- [ ] API sözleşmesini kilitle ve tüm ekiplere dağıt; değişiklikler PR ile. **Son tarih: 10 Eki**
- [ ] Ortak gizli anahtar yönetimi (Groq, Token Factory, Supabase); .env.example güncel. **Son tarih: 10 Eki**
- [ ] Docker image'ının tamamen çalışır hale gelmesi. **Son tarih: 11 Eki**
- [ ] README (İngilizce): kurulum, NVIDIA modelinin kullanımı, Token Factory hız kazancı, kullanılan Nebius servisleri kontrolü. **Son tarih: 26 Eki**
- [ ] Kod dondurma ve v1.0 etiketi. **Son tarih: 26 Eki**
- [ ] Devpost'a gönderim (yedek gün 30 Eki). **Son tarih: 29 Eki**
- [ ] Demo'nun 15 Aralık'a kadar ayakta kalması: izleme ve kredi kontrolü. **Son tarih: 30 Eki sonrası**
