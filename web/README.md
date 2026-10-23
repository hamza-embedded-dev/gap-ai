# GAP-AI Web Client

The web client is a React and TypeScript application built with Vite. It provides:

- Demo session creation and bearer-token handling.
- Natural-language plan entry, parsing, review, and save.
- Plan listing and outcome reporting.
- An insights dashboard with week, previous-week, and all-time views.

The current interface does not implement a browser microphone flow or suggestion acceptance/rescheduling UI. The backend `/voice` and suggestion endpoints are separate capabilities; the ESP32 firmware does not currently upload audio to `/voice`.

## Requirements

- Node.js and npm.
- The GAP-AI backend running locally or a configured API URL.

## Run locally

From this directory:

```bash
npm install
npm run dev
```

By default, the API client uses `/api`, which the Vite development server proxies to `http://127.0.0.1:8000`. Set `VITE_API_URL` to the backend origin when the proxy is not appropriate. `VITE_*` values are included in browser assets and must not contain secrets.

## Checks

```bash
npm test
npm run build
```

`npm test` runs `tests/*.test.mjs`. The additional `src/api/plans.test.ts` file is not selected by that script, so it is not included in this command's test results.

For the backend API payloads and the implementation status of each route, see [../docs/api-contract.md](../docs/api-contract.md). For hosting instructions, see [../docs/DEPLOY.md](../docs/DEPLOY.md).
# GAP-AI Web İstemcisi

GAP-AI projesinin React 19, TypeScript ve Vite ile geliştirilen web kullanıcı arayüzü istemcisidir.

[![Netlify Status](https://api.netlify.com/api/v1/badges/your-site-id/deploy-status)](https://app.netlify.com/sites/your-site-name/deploys)

## 🌐 Canlı Dağıtım (Live Deploy)

- **Canlı Staging / Jüri Demosu URL:** `https://gap-ai-web.netlify.app` *(veya Netlify panelinizde atanan site adı)*
- **HTTPS & CDN:** Netlify Global Edge Network üzerinden SSL sertifikası ile otomatik HTTPS yönlendirmeli olarak dağıtılmaktadır.

---

## 🚀 Yerel Geliştirme (Local Development)

### Gereksinimler
- Node.js 20+
- npm 10+

### Kurulum ve Çalıştırma
```bash
# Web klasörüne geçiş yapın
cd web

# Bağımlılıkları yükleyin
npm install

# Geliştirme sunucusunu başlatın (http://localhost:5173)
npm run dev

# Üretim derlemesi (Production build) alın
npm run build

# Kod kalitesi ve statik analiz (Linter)
npm run lint

# Üretim derlemesini yerelde önizleyin
npm run preview
```

Yerel geliştirmede `/api` istekleri varsayılan olarak `http://localhost:8000` adresindeki FastAPI servisine yönlendirilir (`vite.config.ts`).

---

## ☁️ Netlify Dağıtım Yapılandırması (Continuous Deployment)

Web istemcisi, `web/netlify.toml` dosyası üzerinden sürekli dağıtım (CI/CD) için yapılandırılmıştır.

### Temel Ayarlar (Netlify Dashboard)
Netlify üzerinde yeni bir site bağlarken veya site ayarlarında aşağıdaki değerleri kullanın:

| Ayar | Değer | Açıklama |
| :--- | :--- | :--- |
| **Base directory** | `web` | Monorepo içinde web uygulamasının kök dizini |
| **Build command** | `npm run build` | TypeScript tip denetimi ve Vite üretim derlemesi (`tsc -b && vite build`) |
| **Publish directory** | `dist` | Derleme çıktılarının yer aldığı dizin (`web/dist`) |

### SPA (Single Page Application) Yönlendirmeleri
Sayfa yenilemelerinde veya doğrudan link erişimlerinde 404 hatası oluşmaması için `netlify.toml` içerisinde aşağıdaki SPA kuralı tanımlanmıştır:
```toml
[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

---

## 🔐 Ortam Değişkenleri (Environment Variables)

Proje mimarisi gereği **hiçbir hassas anahtar veya `.env` dosyası Git deposuna commit edilmez**.

Tüm dış API ve ortam konfigürasyonları Netlify yönetim paneli üzerinden tanımlanır.

### E-5 Staging API Entegrasyonu (`VITE_API_URL`)
E-5 görevi ile canlıya alınan staging backend API adresini web arayüzüne bağlamak için şu adımları izleyin:

1. **Netlify Dashboard**'a giriş yapın ve GAP-AI web sitenizi seçin.
2. **Site configuration** > **Environment variables** menüsüne gidin.
3. **Add a variable** butonuna tıklayın:
   - **Key:** `VITE_API_URL`
   - **Value:** `https://api-staging.gap-ai.com` *(veya E-5 görevi sonucunda elde edilen canlı staging API adresi)*
   - **Scopes:** *All scopes* (veya Production ve Deploy Previews için ayrı değerler tanımlanabilir).
4. Değişkeni kaydedin. Yeni derlemelerde (`Deploy Site`) Vite derleme aracı bu adresi istemci koduna statik olarak bağlayacaktır.

> [!IMPORTANT]
> - `VITE_API_URL` adresi tanımlanmadığında istemci varsayılan `/api` proxy yolunu kullanır.
> - Web istemcisi asla Supabase service key veya yapay zeka model API anahtarlarına (Nebius/Groq) doğrudan erişmez; tüm işlemler backend API üzerinden yürütülür.
