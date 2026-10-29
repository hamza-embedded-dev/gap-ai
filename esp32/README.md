# GAP-AI ESP32-S3 Firmware

GAP-AI cihaz firmware'i, ESP-IDF ile geliştirilmiştir. Wi-Fi bağlantısı,
backend sağlık kontrolü, ses kaydı ve oynatma, cihaz butonları ve OLED
arayüzünü destekler.

Bu doküman mevcut ESP32-S3 demo donanımını temel alır. Donanım veya yazılım
revizyonlarına göre pinler ve yapılandırma değişebilir.

## Demo özellikleri

- Wi-Fi bağlantısı ve backend bağlantı kontrolü (`GET /health`)
- Push-to-talk ile ses kaydı
- Kaydedilen sesin backend'e `POST /voice` isteğiyle gönderilmesi
- Backend yanıtındaki konuşma metninin ve sesin işlenmesi
- I2S üzerinden hoparlör ses çıkışı
- OLED ekran desteği
- Plan ve Coach modları
- Kabul ve iptal butonlarıyla desteklenen öneri akışları
- Bağlantı ve etkileşimler için sesli geri bildirim
- Seri port üzerinden cihaz günlükleri

Özelliklerin kullanılabilirliği backend yapılandırmasına, Wi-Fi bağlantısına,
servis erişimine ve bağlı donanıma bağlıdır. Gelecekteki proaktif kişisel
Coach deneyimini tamamlanmış bir özellik olarak değerlendirmeyin.

## Desteklenen donanım

Fiziksel demo kurulumu ESP32-S3 tabanlı kart için hazırlanmıştır.

| Bileşen | Demo bağlantısı |
|---|---|
| OLED ekran | SSD1306, I2C, adres `0x3C` |
| Mikrofon | INMP441, I2S |
| Ses yükselteci | MAX98357A, I2S |
| Kayıt / konuşma butonu | GPIO 38 |
| Kabul butonu | GPIO 1 |
| İptal butonu | GPIO 2 |

### GPIO eşlemesi

Pin tanımları `main/board_pins.h` dosyasındadır.

| Sinyal | GPIO |
|---|---:|
| OLED SCL | 7 |
| OLED SDA | 15 |
| Mikrofon SCK | 4 |
| Mikrofon WS | 5 |
| Mikrofon SD | 6 |
| Hoparlör BCLK | 11 |
| Hoparlör LRC | 12 |
| Hoparlör DIN | 13 |
| Amplifikatör SD | 14 |
| Kayıt / konuşma butonu | 38 |
| Kabul butonu | 1 |
| İptal butonu | 2 |

Butonlar GND'ye bağlanır ve dahili pull-up kullanır. Bağlantıları değiştirmeden
önce `main/board_pins.h` dosyasını ve kullandığın kartın pin özelliklerini kontrol et.

## Gereksinimler

- ESP-IDF v5.1 veya daha yeni; v5.3 önerilir
- ESP32-S3 demo kartı
- 2.4 GHz Wi-Fi ağı
- Uygun USB veri kablosu
- Demo devresine uygun I2S mikrofon, amplifikatör, hoparlör ve OLED
- Çalışan backend ve gerekli servis yapılandırması

## ESP-IDF kurulumu

Resmî kurulum yönergeleri:
https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/

Linux'ta ESP-IDF kurulumundan sonra her yeni terminalde ortamı yükle:

```bash
. ~/esp/esp-idf/export.sh
```

ESP-IDF başka bir dizine kurulduysa komutu o konuma göre değiştir.

USB seri cihazı Linux'ta `/dev/ttyACM0` veya `/dev/ttyUSB0` olarak görünebilir.
Port adı bilgisayara ve karta göre değişir.

## İlk kurulum

Komutları depo kökündeki `esp32/` dizininden çalıştır.

Önce yerel gizli ayar dosyasını oluştur:

```bash
cp main/secrets.example.h main/secrets.h
```

`main/secrets.h` yerel yapılandırma içindir. Gerçek Wi-Fi bilgilerini, API
anahtarlarını veya diğer sırları Git'e eklemeyin. `secrets.h` dosyasının
gitignore kapsamını kontrol edin.

Backend adresi, Wi-Fi bilgileri ve gerekli diğer ayarları kaynak kod ve
yapılandırma dosyalarına göre düzenleyin. Örnek dosyadaki değişken adlarının
gerçek yapılandırmayla eşleştiğini doğrulayın.

## Derleme ve yükleme

```bash
cd ~/Desktop/gap-ai/esp32
idf.py set-target esp32s3
idf.py build
```

`set-target` derleme yapılandırmasını sıfırlayabilir. Hedefi yalnızca gerekli
olduğunda seçin.

Linux'ta cihazı yüklemek ve seri monitörü açmak için:

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

Portun farklı olması durumunda doğru portu kullanın. Monitörden çıkmak için
`Ctrl+]`.

## Çalışma akışı

1. Cihaz açılır ve Wi-Fi bağlantısı kurulur.
2. Backend bağlantısı kontrol edilir.
3. Kullanıcı konuşma butonunu kullanarak ses kaydını başlatır.
4. Firmware kaydı işler ve backend'e gönderir.
5. Backend yanıtı işlenir; mevcut yanıt türüne göre cihaz ses çıkışı üretir.
6. Gerektiğinde kullanıcı öneriyi ilgili butonlarla kabul eder veya iptal eder.

Gerçek davranış, backend'in yanıtına ve cihaz moduna göre değişebilir.

## Backend bağlantı sorunları

- Bilgisayarda çalışan backend için cihazın erişebileceği yerel IP adresini
  kullanın; cihazdan `localhost` kullanılamaz.
- Bilgisayar ile cihazın aynı erişilebilir ağa bağlı olduğunu doğrulayın.
- Backend sağlık kontrolünü ve bilgisayarın güvenlik duvarı kurallarını kontrol edin.
- Wi-Fi, HTTP durum kodları ve ses işleme günlüklerini seri monitörden inceleyin.
- HTTP 200 yanıtı tek başına hoparlörden ses duyulduğunu kanıtlamaz.
- Ses duyulmuyorsa I2S pinlerini, amplifikatör beslemesini, hoparlör bağlantısını
  ve firmware ses günlüklerini kontrol edin.
- HTTPS kullanıldığında sunucu sertifikası doğrulamasının yapılandırılmış
  ortamda çalıştığını doğrulayın.

## Kaynak dosyaları

`esp32/main/` altındaki başlıca dosyalar:

- `main.c` — Başlatma, bağlantı yönetimi ve cihaz etkileşimleri
- `wifi.c` / `wifi.h` — Wi-Fi bağlantısı
- `api.c` / `api.h` — Backend HTTP istemcisi
- `voice.c` / `voice.h` — Ses isteği ve yanıt akışı
- `audio_record.c` / `audio_record.h` — Mikrofon kaydı
- `audio_play.c` / `audio_play.h` — I2S ses oynatma
- `audio_feedback.c` / `audio_feedback.h` — Kısa sesli geri bildirimler
- `audio_limiter.c` / `audio_limiter.h` — Ses seviyesi sınırlama
- `display.c` / `display.h` — OLED ekran
- `gesture.c` / `gesture.h` — Buton hareketleri
- `board_pins.h` — Donanım pinleri
- `settings.c` / `settings.h` — Cihaz ayarları
- `portal.c` / `portal.h` — Yapılandırma portalı
- `discover.c` / `discover.h` — Backend keşif desteği
- `secrets.example.h` — Yerel gizli ayarlar için şablon

Kaynak dosyalar eklerken `main/CMakeLists.txt` içindeki bileşen tanımını
kontrol edin.

## Güvenlik ve ekip kuralları

- Gizli anahtarları ve gerçek kullanıcı bilgilerini commit etmeyin.
- `main/secrets.h` dosyasını paylaşmayın.
- Yerel `sdkconfig` dosyasını incelemeden commit etmeyin; makineye özgü
  ayarlar içerebilir.
- Donanım bağlantılarını değiştirmeden önce pin tanımlarını ve kart
  dokümantasyonunu kontrol edin.
- Başarılı derlemeyi, başarılı yüklemeyi ve fiziksel ses testini ayrı
  doğrulama adımları olarak değerlendirin.
