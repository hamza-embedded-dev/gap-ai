# GAP: Terimler Rehberi

*GAP mimarisinde geçen teknik terimlerin kısa tanımları ve projedeki karşılıkları.*

## 1. Sistem Özeti

| Bileşen | Görevi |
|---|---|
| Web uygulaması (Capacitor ile mobil) | Kullanıcının gördüğü arayüzdür. Yazılı ve sesli girdi alır, grafikleri ve önerileri gösterir. |
| ESP32 | Fiziksel cihazdır. Sesi kaydeder ve butonlarla planın durumunu bildirir. |
| FastAPI | Sistemin merkezindeki sunucudur. İstekleri karşılar ve diğer bileşenleri yönetir. |
| Whisper Large V3 (Groq) | Sesi yazıya çevirir. |
| Nemotron (Nebius Token Factory) | Yazıyı yapılandırılmış bir plana çevirir ve öneri yazar. |
| Analiz motoru | Uyum yüzdesi ve erteleme örüntüsü gibi hesapları yapar. |
| Supabase (PostgreSQL) | Kalıcı veri deposudur. Sistemin uzun süreli hafızasını tutar. |
| Docker ve Nebius | FastAPI uygulamasını paketler ve bulutta çalıştırır. |

## 2. İstemci Tarafı

### Web Uygulaması ve Arayüz Çatıları

Web uygulaması, tarayıcıda çalışan arayüzdür. Bu arayüzü yazmak için bir arayüz çatısı seçilir. Çatı, ekranı buton, kart ve grafik gibi küçük bileşenlerden kurmayı kolaylaştırır. Yaygın seçenekler React, Svelte ve Vue'dur. Bunların her birinin üzerine kurulu, sayfa yönlendirme ve derleme gibi işleri hazır sunan üst çatılar da vardır. Bunlar Next.js (React için), SvelteKit (Svelte için) ve Nuxt'tur (Vue için).

> **GAP'te:** Kullanıcı arayüzü bu çatılardan biriyle yazılır. Hangisinin seçileceği takımın kararıdır. Kullanıcı planını yazar ya da sesli söyler, analiz grafiklerini ve önerileri bu arayüzde görür.

> **Dikkat:** Tarayıcıda mikrofona erişmek için sitenin HTTPS ile açılması gerekir. Seçilen çatı Capacitor ile uyumlu olmalıdır. React, Svelte ve Vue'nun üçü de uyumludur.

### Capacitor

Capacitor, bir web uygulamasını (HTML, CSS ve JavaScript) Android ve iOS için yerel bir uygulama kabuğunun içine paketleyen açık kaynaklı bir araçtır. Ionic ekibi geliştirir. Aynı kodla mağazaya yüklenebilen bir uygulama elde edilir. Mikrofon, kamera ve bildirim gibi telefon özelliklerine eklentilerle erişilir.

> **GAP'te:** Web uygulaması tek kod tabanıyla hem tarayıcıda hem de Android ve iOS uygulaması olarak çalışır. Mobilde mikrofona erişim Capacitor eklentisiyle sağlanır.

> **Dikkat:** Capacitor, derlenmiş statik web dosyalarını paketler. Bu yüzden arayüzün statik çıktı üretecek şekilde ayarlanması gerekir. Next.js için bu ayar static export, SvelteKit için adapter-static'tir. Sunucu tarafında çalışan üst çatı özellikleri uygulamanın içinde çalışmaz.

### ESP32

ESP32, Wi-Fi ve Bluetooth desteği olan, düşük maliyetli bir mikrodenetleyici kartıdır. Üzerine mikrofon, buton ve ekran gibi parçalar bağlanır. Kartın içinde kendi yazılımı çalışır.

> **GAP'te:** GAP'in fiziksel cihazıdır. Mikrofonla sesi kaydeder. Butonlarla "yapıldı", "ertelendi" ve "atlandı" bilgilerini gönderir.

### I2S, WAV ve 16 kHz

I2S, dijital mikrofonun sesi ESP32'ye aktardığı veri yoludur. WAV, sıkıştırılmamış bir ses dosyası biçimidir. 16 kHz ise saniyede alınan örnek sayısını gösterir. Konuşma tanıma için bu değer yeterlidir ve dosya boyutunu küçük tutar.

> **GAP'te:** ESP32 sesi bu biçimde kaydeder ve FastAPI'ye gönderir.

## 3. Sunucu Tarafı

### API

API, bir programın başka bir programdan iş isteyebilmesini sağlayan kurallar bütünüdür. Karşıdaki programın içinde ne olduğunu bilmen gerekmez. Hangi isteği hangi biçimde göndereceğini ve karşılığında ne alacağını API belirler. Örneğin bir hava durumu uygulaması, hava servisinin API'sine şehir adını gönderir ve sıcaklık bilgisini geri alır.

> **GAP'te:** Web uygulaması ve ESP32, FastAPI'nin API'si üzerinden ses ve plan gönderir. FastAPI de Groq ve Nebius Token Factory'nin API'lerini kullanır.

### HTTP ve HTTPS

HTTP, internet üzerinde iki programın birbiriyle konuşurken kullandığı ortak dildir. İsteği gönderen tarafa istemci, cevap veren tarafa sunucu denir. İstemci bir istek yollar, sunucu da bir cevap döner. HTTPS, aynı konuşmanın şifrelenmiş halidir. Veriyi yolda başkaları okuyamaz.

> **GAP'te:** ESP32 ve web uygulaması FastAPI ile HTTPS üzerinden konuşur. Ses ve plan bilgisi bu sayede şifreli gider.

### GET ve POST

Her HTTP isteği belirli bir türle gönderilir. Bu türe metot denir. GET, bir şeyi okumak içindir. Örneğin "planlarımı getir" bir GET isteğidir. POST ise sunucuya yeni bir veri göndermek içindir. Örneğin "bu ses kaydını işle" ya da "bu planı kaydet" birer POST isteğidir. POST isteğinin içinde gönderilecek veri de bulunur. Bu veri bir ses dosyası ya da bir JSON olabilir.

> **GAP'te:** ESP32 sesi POST ile /voice adresine yollar. Butona basıldığında planın sonucu da POST ile /plans/{id}/outcome adresine gönderilir.

### REST

REST, API'leri düzenli biçimde tasarlamak için kullanılan yaygın bir yaklaşımdır. HTTP üzerine kurulur. Plan, sonuç ve kullanıcı gibi her şeyin kendi adresi vardır. İsteğin türü de o adreste ne yapılacağını belirtir. Okumak için GET, göndermek için POST kullanılır. Veri çoğunlukla JSON biçiminde taşınır. Bu yaklaşımı izleyen API'lere REST API denir.

> **GAP'te:** FastAPI'nin kendi API'si de, Groq ve Nebius Token Factory API'leri de REST yaklaşımıyla çalışır. Bu yüzden hepsiyle aynı yöntemle konuşulur. Önce bir HTTPS isteği gönderilir, sonra JSON bir cevap alınır.

### Endpoint

Endpoint, bir API'nin tek tek adreslerinden her biridir. Her endpoint belirli bir işi yapar. Örneğin /voice adresi ses kaydını alır. /plans/{id}/outcome adresi ise bir planın sonucunu kaydeder. Süslü parantez içindeki {id} yerine planın gerçek numarası yazılır.

> **GAP'te:** FastAPI'nin ana endpoint'leri şunlardır. /parse yazıyı plana çevirir, /voice sesi alır, /plans/{id}/outcome planın sonucunu kaydeder.

### FastAPI

FastAPI, Python ile API geliştirmek için kullanılan modern bir çatıdır. Aynı anda birçok isteği karşılayabilir. Kendi dokümantasyon sayfasını otomatik üretir. Gelen verinin doğru biçimde olup olmadığını da Pydantic ile denetler.

> **GAP'te:** Sistemin merkezidir. Gelen isteği karşılar, sesi Whisper'a, yazıyı Nemotron'a gönderir. Sonuçları Supabase'e kaydeder ve istemciye cevap döner.

### JSON ve Pydantic

JSON, veriyi anahtar ve değer çiftleriyle yazan bir metin biçimidir. Örneğin niyet "koşu", saat "19:00" olarak yazılır. Bilgisayarlar bu biçimi kolayca okur. Pydantic ise Python'da bir verinin beklenen şemaya uyup uymadığını denetleyen bir kütüphanedir. Şemaya uymayan veriyi reddeder.

> **GAP'te:** Nemotron'dan gelen JSON, veritabanına yazılmadan önce Pydantic ile doğrulanır. Model bazen şemaya uymayan bir çıktı üretebilir. Böyle bir durumda FastAPI aynı isteği modele yeniden gönderir ve birkaç denemeye kadar devam eder. Doğru bir çıktı yine alınamazsa kullanıcıya hata mesajı gösterilir ve bozuk veri kaydedilmez.

### Docker

Bir uygulamanın çalışması için belirli bir Python sürümüne, belirli kütüphanelere ve ayarlara ihtiyaç vardır. Docker, uygulamayı bu ihtiyaçlarıyla birlikte konteyner adı verilen tek bir pakete koyar. Paketin nasıl hazırlanacağı Dockerfile adlı bir dosyada yazılıdır. Konteyner taşınabilirdir. Aynı paket geliştiricinin bilgisayarında da, Nebius'ta da, başka bir bulut sağlayıcıda da değişmeden çalışır. Bu sayede "bende çalışıyor ama sende çalışmıyor" sorunu ortadan kalkar. Sunucuyu başka bir yere taşımak da paketi yeni yere yüklemekten ibaret olur.

> **GAP'te:** FastAPI uygulaması Dockerfile ile paketlenir ve Nebius'a konteyner olarak yüklenir. Takımdaki herkes aynı paketi kendi bilgisayarında çalıştırıp test edebilir.

### Nebius ve Sunucusuz (Serverless) Yapı

Nebius, yapay zekâ işlerine odaklanan bir bulut sağlayıcısıdır. Güçlü ekran kartlarına (GPU) sahip sunucular sunar. Sunucusuz yapıda sunucuyu kurmak, güncellemek ve izlemek senin işin olmaz. Konteyneri yüklersin ve platform onu çalıştırır. İstek sayısı artarsa platform kopya sayısını artırır, azalırsa düşürür. Adı yanıltıcı olabilir. Sunucular yine vardır ama yönetimleri sana ait değildir. Ücretlendirme genellikle kullanıma göre yapılır.

> **GAP'te:** FastAPI sunucusu Nebius'ta 7/24 çalışır. Hackathon için verilen Nebius kredisi bu kullanımdan düşer.

> **Dikkat:** Sunucu yeniden başladığında bellekteki geçici veriler silinebilir. Bu yüzden kalıcı olması gereken her şey Supabase'e yazılır.

### Önbellek, Zamanlayıcı ve Durumsuz Sunucu

Önbellek, sık kullanılan verinin hızlı erişim için bellekte geçici olarak tutulmasıdır. Zamanlayıcı, belirli aralıklarla kendiliğinden çalışan bir görevdir. Durumsuz (stateless) sunucu ise kalıcı veriyi kendi içinde saklamayan, her isteği bağımsız olarak işleyen sunucudur.

> **GAP'te:** Analiz sonuçları kısa süre önbellekte tutulabilir. Zamanlayıcı görev, kullanıcının erteleme örüntülerini düzenli olarak kontrol eder.

## 4. Yapay Zekâ Tarafı

### Konuşmayı Yazıya Çevirme (STT)

STT, "Speech-to-Text" ifadesinin kısaltmasıdır. Ses kaydını yazıya dönüştürme işlemi anlamına gelir.

> **GAP'te:** "Akşam koşuya gideceğim" gibi bir konuşma önce yazıya çevrilir. Ardından bu yazı Nemotron'a verilir.

### Whisper (Large V3)

Whisper, OpenAI'nin geliştirdiği açık kaynaklı bir ses tanıma modelidir. Türkçe dahil birçok dili tanır ve gürültülü kayıtlarda da iyi sonuç verir. Large V3, modelin büyük ve doğruluğu yüksek sürümüdür.

> **GAP'te:** Web uygulamasından ya da ESP32'den gelen sesi yazıya çevirir.

### Groq

Groq, yapay zekâ modellerini çok hızlı çalıştırmak için özel çipler geliştiren bir şirkettir. Kendi modelini yapmaz. Whisper gibi açık kaynaklı modelleri hızlı çalıştırır ve bunu API olarak sunar. Groq'un API'si OpenAI'nin API'siyle uyumludur. Yani OpenAI için yazılmış kodlar küçük değişikliklerle Groq'ta da çalışır. Ses dosyaları api.groq.com adresindeki transcriptions endpoint'ine gönderilir.

> **GAP'te:** FastAPI sesi doğrudan Groq API'sine gönderir ve Whisper Large V3 yazıyı geri döner. Dosya boyutu sınırı 25 MB'dır. Groq sesi işlerken 16 kHz mono'ya indirir. ESP32 zaten 16 kHz kaydettiği için ek bir dönüşüm gerekmez.

> **Dikkat:** Groq ile Elon Musk'ın yapay zekâsı Grok farklı şeylerdir.

### LLM, Nemotron ve Nebius Token Factory

LLM (büyük dil modeli), çok büyük miktarda metinle eğitilmiş, metni anlayıp yeni metin üretebilen bir yapay zekâ modelidir. Nemotron, NVIDIA'nın açık kaynaklı dil modeli ailesidir. Token, modelin metni işlerken kullandığı birimdir ve yaklaşık bir kelimeye ya da kelime parçasına denk gelir. Kullanım miktarı token ile ölçülür. Nebius Token Factory ise bu hazır modelleri token başına ücretle API üzerinden sunan hizmettir.

> **GAP'te:** Nemotron iki iş yapar. Birincisi, "Akşam koşuya gideceğim" cümlesini tarih, saat ve kategori içeren yapılandırılmış bir plana çevirmektir. İkincisi, analiz motorunun verdiği sayıları okuyup kullanıcıya bir öneri yazmaktır.

> **Dikkat:** Hesaplamayı model yapmaz. Yüzde ve süreleri analiz motoru hesaplar, model yalnızca yorumlar. Dil modelleri sayısal hesaplarda hata yapabildiği için iş bölümü bu şekilde kurulmuştur.

## 5. Veri Tarafı

### Supabase ve PostgreSQL

PostgreSQL, verinin tablolar halinde tutulduğu açık kaynaklı bir veritabanıdır. Supabase ise PostgreSQL üzerine kurulu, yönetilen bir platformdur. Veritabanını hazır olarak sunar ve kullanıcı girişi (Auth) gibi ek özellikler de içerir.

> **GAP'te:** Kalıcı depolama burasıdır. Kullanıcılar, planlar ve sonuçlar (yapıldı, ertelendi, atlandı) ayrı tablolarda tutulur. Bu veri sistemin uzun süreli hafızasını oluşturur. Yapay zekâ modelleri veritabanına doğrudan bağlanmaz. Veriye erişim yalnızca FastAPI üzerinden olur.

### Kalıcı ve Geçici Depolama

Kalıcı depolamada veri, sunucu kapansa bile korunur. Geçici depolama hızlıdır ama sunucu yeniden başladığında veri silinebilir.

> **GAP'te:** Kalıcı veri Supabase'te tutulur. Geçici ve yeniden üretilebilir veri Nebius tarafında tutulur.

## 6. Bileşenler Arası İletişim

| Kimden | Kime | Yöntem | Taşınan veri |
|---|---|---|---|
| Web uygulaması, ESP32 | FastAPI | HTTPS POST | Yazı, ses ve buton bilgisi |
| FastAPI | Groq (Whisper Large V3) | REST API | Ses gider, yazı gelir |
| FastAPI | Nebius Token Factory (Nemotron) | REST API | Komut ve bağlam gider, JSON gelir |
| FastAPI | Supabase (PostgreSQL) | Veritabanı bağlantısı | Plan ve sonuç kaydı yazılır, geçmiş okunur |
| Analiz motoru | Supabase ve Nemotron | FastAPI içinden | Hesaplanan sayılar yoruma gönderilir |

## 7. Örnek Akış: Sesli Plan

Kullanıcı ESP32'ye "Akşam koşuya gideceğim" diyor. Arka planda şunlar olur:

1. **Kayıt:** ESP32 sesi 16 kHz WAV olarak kaydeder ve HTTPS ile FastAPI'ye gönderir.
2. **Yazıya çevirme:** FastAPI sesi Groq'a iletir ve Whisper yazıyı geri döner.
3. **Bağlam:** FastAPI, Supabase'ten kullanıcının saat dilimini ve benzer geçmiş planlarını okur.
4. **Ayrıştırma:** Yazı, güncel saat ve bağlam Nemotron'a gönderilir. Model yapılandırılmış bir JSON döner.
5. **Doğrulama ve kayıt:** Pydantic JSON'ı doğrular. FastAPI planı Supabase'e kaydeder ve cihaza "Başarılı" yanıtı döner.
6. **Öneri:** Kullanıcı sporu üç kez atlarsa analiz motoru bunu tespit eder. Nemotron "Sabaha alalım mı?" gibi bir öneri yazar ve web uygulaması bunu gösterir.

## 8. Sık Karıştırılan Terimler

| Terimler | Fark |
|---|---|
| API ve endpoint | API, bir programın sunduğu kuralların tamamıdır. Endpoint ise bu API'nin tek tek adresleridir. |
| GET ve POST | GET veri okumak içindir. POST ise veri göndermek içindir. |
| Arayüz çatısı ve Capacitor | React, Svelte ve Vue gibi çatılar arayüzü yazmak için kullanılır. Capacitor ise ortaya çıkan web uygulamasını Android ve iOS uygulamasına paketler. |
| Docker ve sunucu | Sunucu, uygulamanın çalıştığı makinedir. Docker ise uygulamayı bağımlılıklarıyla birlikte paketleyen konteyner biçimidir. |
| Supabase ve PostgreSQL | PostgreSQL veritabanının kendisidir. Supabase onu yöneten ve ek özellikler sunan platformdur. |
| Groq ve Grok | Groq, modelleri hızlı çalıştıran bir altyapı şirketidir. Grok ise başka bir şirketin yapay zekâ sohbet modelidir. |
| Whisper ve Nemotron | Whisper sesi yazıya çevirir. Nemotron yazıyı plana çevirir ve öneri yazar. |
| Groq ve Token Factory | İkisi de yapay zekâ modellerini API ile sunar. GAP'te Groq ses tanıma (Whisper) için, Nebius Token Factory ise dil modeli (Nemotron) için kullanılır. |
