# GAP-AI ESP32 Firmware

ESP-IDF tabanlı cihaz firmware'i. Wi-Fi'a bağlanır, backend'e periyodik `GET /health` atar ve sesli asistan döngüsünü çalıştırır: kayıt butonu basılı tutulurken INMP441 mikrofondan ses kaydeder, `POST /voice`'a gönderir (Groq Whisper → Nemotron → Groq TTS), gelen sesli yanıtı MAX98357A hoparlörden çalar ve transkript/yanıtı SSD1306 OLED'de gösterir. Sonuç butonu (D1-2) henüz yok.

## Desteklenen kartlar

Kod çipe özel bir şey kullanmıyor; hedef çip derleme sırasında seçiliyor.

| Çip | Hedef | Durum |
|---|---|---|
| ESP32 (classic) | `esp32` | Donanımda test edildi |
| ESP32-S3 | `esp32s3` | Derleniyor |
| ESP32-C3 | `esp32c3` | Desteklenmeli (RISC-V araç zinciri gerekir) |
| ESP32-S2 / C6 | `esp32s2` / `esp32c6` | Desteklenmeli |

Gereksinimler: en az **4 MB flash** ve **2.4 GHz** Wi-Fi (ESP32'ler 5 GHz ağlara bağlanamaz).

## ESP-IDF kurulumu

**ESP-IDF v5.3** kullanıyoruz (en az v5.1). Ekipte herkes aynı ana sürümü kullansın.

### Windows

1. [ESP-IDF Windows Installer](https://dl.espressif.com/dl/esp-idf/) ile **v5.3.x** kur. Kurulumda kendi kartının çipini de seç (ör. ESP32-S3 kullanıyorsan `esp32s3`).
2. Repoyu **kısa, boşluksuz ve Türkçe karakter içermeyen** bir yola klonla, ör. `C:\dev\gap-ai`. `C:\Users\Şükrü\Masaüstü\...` gibi yollar ESP-IDF derlemesini bozar.
3. Komutları Başlat menüsündeki **"ESP-IDF 5.3 PowerShell"** (veya CMD) penceresinden çalıştır; normal PowerShell'de `idf.py` bulunmaz.
4. Kart görünmüyorsa USB-seri sürücüsünü kur: CP210x (Silicon Labs) veya CH340 (WCH). Port **Aygıt Yöneticisi → Bağlantı noktaları (COM ve LPT)** altında `COM3` gibi görünür.

### Linux

```bash
mkdir -p ~/esp && cd ~/esp
git clone -b release/v5.3 --recursive https://github.com/espressif/esp-idf.git
./esp-idf/install.sh esp32,esp32s3,esp32c3
```

Her yeni terminalde ortamı yükle:

```bash
. ~/esp/esp-idf/export.sh
```

Port genelde `/dev/ttyUSB0` (CP210x/CH340) veya `/dev/ttyACM0` (dahili USB'li S3/C3). Erişim izni yoksa kullanıcını `dialout` (Debian/Ubuntu) veya `uucp` (Arch) grubuna ekleyip oturumu yeniden aç.

## İlk kurulum

1. Ayar dosyasını kopyala ve kendi bilgilerini yaz:

   ```bash
   cp main/secrets.example.h main/secrets.h
   ```

   Windows'ta: `copy main\secrets.example.h main\secrets.h`

   `secrets.h` gitignore'da; **asla commit etme**. Dosya yoksa derleme açıklayıcı bir hatayla durur.

2. Kartının çipini seç (her klonda bir kez, ya da kart değiştirince):

   ```bash
   idf.py set-target esp32
   ```

   ESP32-S3 için `esp32s3`, ESP32-C3 için `esp32c3`. `set-target` derleme klasörünü sıfırlar.

## Donanım bağlantısı

Pinler tek bir dosyada: `main/board_pins.h`. Şu an yalnızca **ESP32-S3-DevKitC-1** için tanımlı ve donanımda test edildi. Başka bir kartta firmware derlenir ve `/health` döngüsü çalışır ama ses donanımı kapalı kalır; kendi kartın için `board_pins.h`'a bir blok ekle.

| Modül | Pin | ESP32-S3 |
|---|---|---|
| SSD1306 OLED 128x32 (I2C, 0x3C) | SCL / SDA / VCC / GND | GPIO7 / GPIO15 / 3V3 / GND |
| INMP441 mikrofon (I2S) | SCK / WS / SD / L/R / VDD / GND | GPIO4 / GPIO5 / GPIO6 / GND / 3V3 / GND |
| MAX98357A amfi (I2S) | BCLK / LRC / DIN / SD / VIN / GND | GPIO11 / GPIO12 / GPIO13 / GPIO14 / 5V / GND |
| Kayıt butonu (bas-konuş) | bir ucu GND | GPIO2 |
| Sonuç butonu (D1-2, henüz kullanılmıyor) | bir ucu GND | GPIO1 |

- MAX98357A'nın **GAIN** pini boş kalır (9 dB). Hoparlör 8 Ω / 0.5 W; yazılım ses seviyesi `AUDIO_PLAY_VOLUME` (0.50) ile sınırlı, bu değeri GAIN'i düşürmeden artırma.
- Amfinin VIN–GND arasına 100–470 µF kondansatör koy.
- Kaçınılacak pinler: 0/3/45/46 (strapping), 19/20 (USB), 43/44 (UART0), 48 (RGB LED), 35–37 (oktal PSRAM).
- ESP32-S3'te PSRAM `sdkconfig.defaults.esp32s3` ile açılır (oktal; N8R2 gibi quad-PSRAM modüllerde yerel `sdkconfig`'te `CONFIG_SPIRAM_MODE_QUAD=y` seç). 320 KB ses kaydı PSRAM olmadan Wi-Fi + TLS ile birlikte sığmaz.

## Kullanım

1. `secrets.h` içine `DEVICE_TOKEN` yaz (`backend/scripts/create_access_token.py` ile üretilir). Boşsa cihaz ekranda "Ayar eksik" der.
2. Kayıt butonunu **basılı tut**: kısa bir bip sesinden sonra "Dinliyorum..." görünür. En fazla 10 saniye konuş, butonu bırakınca gönderilir.
   Buton yoksa klavyeyle: `idf.py -p <port> monitor` aç, **Enter**'a bas (bip + "Dinliyorum..."), konuş, tekrar **Enter** ile gönder (10 sn'de kendiliğinden durur).
3. Ekranda "Düşünüyorum..." sonrası yanıt metni görünür ve hoparlörden okunur. Backend TTS kapalıysa veya başarısız olursa yalnızca metin gösterilir.

Cihaz `/voice`'a `Accept: audio/wav` gönderir; yanıt WAV'ı indirilirken doğrudan hoparlöre akıtılır (örnekleme hızı WAV başlığından okunur). Ayrıntı: `docs/api-contract.md`.

## Derle, yükle, izle

Bütün komutlar `esp32/` klasöründen çalışır.

```bash
idf.py build
```

Linux:

```bash
idf.py -p /dev/ttyUSB0 flash monitor
```

Windows:

```powershell
idf.py -p COM3 flash monitor
```

Monitörden çıkmak için `Ctrl+]`. Yükleme bağlanamazsa kart üzerindeki **BOOT** tuşuna basılı tutup yüklemeyi tekrar başlat.

Beklenen çıktı:

```text
I (...) gap: GAP device starting on esp32 (rev 3.1, 2 core(s)), ESP-IDF v5.3.6
I (...) net: Connecting to "MyWifi"...
I (...) net: Connected, IP: 192.168.1.42
I (...) api: GET /health -> HTTP 200 {"status":"ok","version":"0.1.0"}
```

`/health` her 30 saniyede bir tekrarlanır. Wi-Fi koparsa cihaz artan aralıklarla (1 sn → 30 sn) yeniden bağlanmayı dener.

## Backend'e bağlanma

`BACKEND_BASE_URL` sonunda `/` olmadan yazılır.

- **Kendi bilgisayarındaki backend (HTTP):** cihaz `localhost`'a erişemez, bilgisayarın yerel IP'sini yaz (ör. `http://192.168.1.50:8000`). Backend'i ağa açık başlat:

  ```bash
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```

  Windows'ta Güvenlik Duvarı izin isterse **Özel ağlar** için izin ver. Linux'ta firewalld açıksa portu geçici olarak aç (yeniden başlatınca kapanır): `sudo firewall-cmd --add-port=8000/tcp`; ufw kullanıyorsan `sudo ufw allow 8000/tcp`. Cihaz logunda `ESP_ERR_HTTP_CONNECT` görürsen ilk bakılacak yer güvenlik duvarıdır. IP'ni Windows'ta `ipconfig`, Linux'ta `ip -4 addr` ile bulabilirsin. Bilgisayar ve kart aynı ağda olmalı.

- **Staging (HTTPS):** `https://...` adresi yazman yeterli. Sunucu sertifikası ESP-IDF'in dahili kök CA paketiyle doğrulanır; ayrıca sertifika dosyası gerekmez.

## Dosya yapısı

```text
esp32/
├── CMakeLists.txt         ESP-IDF proje tanımı
├── sdkconfig.defaults     Ekip için ortak ayarlar (flash, TLS)
├── sdkconfig.defaults.esp32s3  Yalnız S3: PSRAM
└── main/
    ├── main.c             Açılış: NVS, ekran, Wi-Fi, bas-konuş döngüsü, periyodik /health
    ├── board_pins.h       Tüm GPIO numaraları (kart başına bir blok)
    ├── wifi.c / wifi.h    Wi-Fi bağlantısı ve yeniden bağlanma
    ├── api.c / api.h      Backend HTTP(S) istemcisi
    ├── audio_record.c/.h  INMP441 I2S kayıt → 16 kHz mono WAV
    ├── audio_play.c/.h    MAX98357A I2S çalma (ses sınırı, bas kesme, SD ile susturma)
    ├── display.c/.h       SSD1306 OLED (Türkçe harfler aksansız gösterilir)
    ├── voice.c/.h         Bas-konuş: kayıt → POST /voice → yanıtı çal ve göster
    └── secrets.example.h  secrets.h şablonu
```

ESP-IDF'te kaynak kodlar `main/` altında durur. Görev planında geçen `esp32/src/...` yolları burada `esp32/main/...` olarak karşılık bulur (ör. `src/buttons.*` → `main/buttons.*`). Yeni bir `.c` dosyası eklediğinde `main/CMakeLists.txt` içindeki `SRCS` listesine de ekle.

## Ekip için kurallar

- `sdkconfig` commit edilmez; çipe ve makineye özeldir. Herkese lazım olan bir ayar varsa `sdkconfig.defaults`'a ekle.
- GPIO pinlerini koda sabit gömme; kartlar arasında farklılar. Hepsi `main/board_pins.h`'ta.
- Log mesajlarını ASCII tut. Türkçe karakterler Windows konsolunda bozuk görünebilir.
