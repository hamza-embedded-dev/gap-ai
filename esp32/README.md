# GAP-AI ESP32 Firmware

ESP-IDF tabanlı cihaz firmware'i. Şu an Wi-Fi'a bağlanıyor ve backend'e `GET /health` isteği atıyor (D1-1). Butonlar (D1-2), ekran (D1-3) ve mikrofon (D2) bu iskeletin üzerine eklenecek.

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
└── main/
    ├── main.c             Açılış: NVS, Wi-Fi, periyodik /health
    ├── wifi.c / wifi.h    Wi-Fi bağlantısı ve yeniden bağlanma
    ├── api.c / api.h      Backend HTTP(S) istemcisi
    └── secrets.example.h  secrets.h şablonu
```

ESP-IDF'te kaynak kodlar `main/` altında durur. Görev planında geçen `esp32/src/...` yolları burada `esp32/main/...` olarak karşılık bulur (ör. `src/buttons.*` → `main/buttons.*`). Yeni bir `.c` dosyası eklediğinde `main/CMakeLists.txt` içindeki `SRCS` listesine de ekle.

## Ekip için kurallar

- `sdkconfig` commit edilmez; çipe ve makineye özeldir. Herkese lazım olan bir ayar varsa `sdkconfig.defaults`'a ekle.
- GPIO pinlerini koda sabit gömme; kartlar arasında farklılar. Pinler eklenirken (D1-2, D2) tek bir başlık dosyasında toplanacak.
- Log mesajlarını ASCII tut. Türkçe karakterler Windows konsolunda bozuk görünebilir.
