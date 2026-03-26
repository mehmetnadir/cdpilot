# Browserless.io Derinlemesine Analiz & cdpilot Cloud Stratejisi

> Araştırma Tarihi: 2026-03-25
> Amaç: Browserless iş modelini anlamak, cdpilot Cloud için farklılaşma stratejisi ve MVP planı oluşturmak.

---

## 1. Browserless Teknik Yapı

### 1.1 Mimari

Browserless, Docker container içinde çalışan bir headless browser platformu. Temel mimari:

```
İstemci (Puppeteer/Playwright/REST)
    │
    ├── WebSocket (wss://) → Canlı CDP bağlantısı
    ├── REST API (https://) → Tek seferlik işlemler (screenshot, PDF, content)
    └── BrowserQL (GraphQL) → Hibrit otomasyon sorguları
    │
    ▼
Browserless Gateway (Node.js + TypeScript)
    │
    ├── Bağlantı havuzu (connection pooling)
    ├── Kuyruk yönetimi (queue management)
    ├── Oturum izolasyonu
    └── Kaynak limitleri (CPU, RAM, süre)
    │
    ▼
Chrome/Chromium/Firefox/WebKit Instance(lar)
    └── Her bağlantı → izole browser context
```

### 1.2 API Yapısı

**3 farklı protokol:**

| Protokol | Kullanım | Endpoint Örneği |
|----------|----------|-----------------|
| **WebSocket (CDP)** | Puppeteer/Playwright bağlantısı | `wss://production-sfo.browserless.io/?token=X` |
| **REST API** | Screenshot, PDF, content çekme | `POST /screenshot?token=X` |
| **BrowserQL (GraphQL)** | Hibrit otomasyon senaryoları | `POST /chrome/bql?token=X` |

**Bölgesel dağıtım:** 3 bölge
- ABD Batı: `production-sfo.browserless.io`
- İngiltere: `production-lon.browserless.io`
- Hollanda: `production-ams.browserless.io`

**Desteklenen tarayıcılar:**
- Chromium (Puppeteer/CDP)
- Chrome stable (Puppeteer/CDP)
- Firefox (Playwright)
- WebKit (Playwright)

### 1.3 Session Yönetimi

- Her WebSocket bağlantısı = 1 session
- Session başlangıcında Chrome instance oluşturulur
- Session süresi plana göre sınırlı (1 dk - 60 dk)
- Session-reconnect = yeni bağlantı, yeni unit tüketimi
- `headless`, `stealth`, `humanlike` flag'leri ile özelleştirme
- Launch config JSON payload ile geçilebilir

### 1.4 Fiyatlandırma Detayları

**Unit Tanımı:** 1 Unit = 30 saniyeye kadar 1 browser bağlantısı. 30+ saniye → her 30 saniyede +1 unit.

| Plan | Fiyat (yıllık) | Unit/ay | Eşzamanlı Tarayıcı | Session Süresi | Overage |
|------|----------------|---------|---------------------|----------------|---------|
| **Free** | $0 | 1.000 | 2 | 1 dk | — |
| **Prototyping** | $25/ay | 20.000 | 15 | 15 dk | $0.0020/unit |
| **Starter** | $140/ay | 180.000 | 40 | 30 dk | $0.0017/unit |
| **Scale** | $350/ay | 500.000 | 100 | 60 dk | $0.0015/unit |
| **Enterprise** | Özel | Milyonlarca | Yüzlerce+ | Özel | Özel |

**Ek maliyetler:**
- Residential proxy: 6 unit/MB
- CAPTCHA çözme: 10 unit/başarılı çözüm

**Kritik bilgi:** Kullanıcıların %98'inin session'ları 30 saniyenin altında → çoğu işlem 1 unit.

### 1.5 Self-Hosted vs Hosted

| Özellik | Cloud (Hosted) | Self-Hosted (OSS) | Self-Hosted (Enterprise) |
|---------|---------------|-------------------|--------------------------|
| Lisans | SaaS abonelik | SSPL-1.0 | Ticari lisans |
| Ticari kullanım | Evet | Hayır (rakip ürün yasak) | Evet |
| Yönetim | Tam yönetilen | Kendin yönet | Kendin yönet + destek |
| Özellikler | Tam | Temel | Tam (lisans anahtarı) |
| Proxy/CAPTCHA | Dahil | Yok | Dahil |
| Maliyet | Abonelik | Altyapı maliyeti | Lisans + altyapı |

---

## 2. Browserless Büyüme Hikayesi

### 2.1 Kurucu: Joel Griffith

- **Geçmiş:** Kendi kendini yetiştirmiş mühendis, orijinal eğitimi caz trompetçiliği
- **Konum:** Portland, Oregon, ABD
- **5-6 başarısız B2C girişimden sonra** developer-odaklı altyapıya yöneldi

### 2.2 Doğuş Hikayesi (2017)

Joel bir yan proje (ürün istek listesi uygulaması) geliştirirken Puppeteer ile web scraping yapıyordu. Sürekli sorunlarla karşılaştı:
- Chrome çökmeleri
- Bellek sızıntıları
- Docker komplikasyonları

**Aydınlanma anı:** "Başka geliştiriciler de aynı sorunları yaşıyor" → Altyapı sorununu çözmeye karar verdi.

### 2.3 Gelir Kronolojisi

| Dönem | MRR | Not |
|-------|-----|-----|
| 2017 sonu | $200 | İlk müşteri, altyapı maliyeti $50 |
| 2018 sonu | ~$1.000 | Yavaş organik büyüme |
| 2020 ortası | ~$42K | $500K ARR → tam zamanlıya geçiş |
| Solo dönem sonu | $60K | Tek kişilik ölçekleme sınırı |
| 2024 | $108K | ~$1.3M ARR, 3.000 müşteri |
| 2025-2026 | ~$290K | ~$3.5M ARR'a yaklaşıyor |

**Başlangıç maliyeti:** Sadece $500

### 2.4 Müşteri Kazanım Stratejisi

**İlk 10 müşteri:**
1. Puppeteer'ın GitHub Issues sayfasında soruları yanıtladı
2. Stack Overflow'da çözüm üretti
3. Reddit developer forumlarında yardım etti
4. **Agresif satış yapmadı** — uzmanlık gösterdi, Browserless'ı alternatif olarak önerdi

**Dikkat çekici erken kazanım:** Indeed.com bir Gmail adresiyle kaydoldu, ürünü dahili test etti, sonra doğrudan ulaştı. Joel'ün içerik çalışmalarını zaten görmüşlerdi.

### 2.5 Büyüme Motorları

**1. İçerik Moat'ı (8 yıllık bileşik getiri):**
- Blog yazıları, forum yanıtları, açık kaynak katkıları
- "Bir kez yaz, sürekli çalışsın" felsefesi
- $3.5M ARR'da neredeyse TÜM müşteri kazanımı inbound/organik

**2. SEO + AI adaptasyonu:**
- Geleneksel Google trafiği stabil kaldı
- ChatGPT/AI overviews için soru-cevap formatına geçiş
- YouTube ve X (Twitter) kanallarına genişleme

**3. Topluluk varlığı:**
- GitHub'da aktif
- Geliştirici forumlarında sürekli yardım
- 8 yıllık birikimle "kurucu erişimi" avantajı

### 2.6 Rekabete Dayanma

**Google Cloud (2 yıl öncesi uyarı):**
- Joel: "Bitti, Google Cloud yapıyor" diye düşündü
- Sonuç: Müşteriler kurucuyla birebir ilişkiyi tercih etti
- "İlişki tabanlı bir iş, kimin arkasında olduğunu bilmek istiyorlar"

**Browserbase ($60M fonlama):**
- Joel'ün büyüme eğrisi hiç etkilenmedi
- 8 yıllık içerik + topluluk + müşteri ilişkisi, paranın kopyalayamayacağı bir hendek

### 2.7 Ekip & Operasyon

- **Solo dönem:** $60K MRR'a kadar tek kişi
- **Polychrome ortaklığı:** İşe alım, finans, hukuk delegasyonu
- **Mevcut ekip:** <10 kişi, %60'ı mühendislik
- **Günlük kayıt:** 250-300 yeni kullanıcı
- **Ödeme yapan:** 3.000-4.000 müşteri
- **Fonlama:** $0 — %100 bootstrapped

---

## 3. Browserless'ın Zayıf Noktaları

### 3.1 Teknik Zayıflıklar

| Zayıflık | Detay |
|----------|-------|
| **Bot tespiti sınırlı** | Cloudflare gibi gelişmiş korumalardan geçemiyor, "sadece ilk bebek adımı" |
| **Tek dosya mimarisi (eski v1)** | v2 ile düzeldi ama hâlâ karmaşık |
| **Selenium desteği kaldırıldı** | v2'de düşürüldü, legacy kullanıcılar etkilendi |
| **WebSocket-only canlı oturum** | REST API stateless, canlı etkileşim için WS zorunlu |
| **Observability zayıf** | Browserbase'e kıyasla daha az dahili debugging aracı |

### 3.2 Fiyatlandırma Sorunları

| Sorun | Detay |
|-------|-------|
| **Unit tüketimi belirsiz** | 30 saniyelik pencere, uzun işlemlerde hızla tükenir |
| **Proxy pahalı** | 25GB data = ~$500/ay → GB başına ~$20 |
| **Session-reconnect = yeni unit** | Bağlantı kopması durumunda çift ödeme |
| **CAPTCHA maliyeti** | 10 unit/çözüm, yoğun kullanımda ciddi maliyet |
| **2024'te fiyat modeli değişimi** | Unit-based'e geçiş, bazı kullanıcıları rahatsız etti |

### 3.3 Kullanıcı Şikayetleri

- **Dik öğrenme eğrisi:** Proxy yönetimi, headless yapılandırma, JS işleme karmaşık
- **Etik endişeler:** HackerNews'te "Abuse as a Service" eleştirisi aldı
- **Self-hosted kısıtlama:** SSPL lisans, ticari kullanımda açık kaynak versiyonu kullanılamaz
- **BrowserQL öğrenme yükü:** Ek soyutlama katmanı, karmaşıklık artırıyor

### 3.4 Rakiplerine Karşı Zayıf Noktalar

| Rakip | Browserless'ın Dezavantajı |
|-------|---------------------------|
| **Browserbase** | AI-native entegrasyonlar eksik (CrewAI, browser-use, Stagehand) |
| **Cloudflare Browser Rendering** | Global CDN avantajı yok |
| **Lightpanda** | 11x daha yavaş, 9x daha fazla bellek |
| **Playwright MCP** | Doğrudan MCP desteği yok (aracı katman gerekiyor) |
| **Steel** | Stealth konusunda daha zayıf |

---

## 4. cdpilot Cloud İçin Farklılaşma Fırsatları

### 4.1 cdpilot'un Mevcut Avantajları

| Avantaj | Açıklama |
|---------|----------|
| **Sıfır bağımlılık** | Pure Python stdlib + Node.js entry — hafif, hızlı başlangıç |
| **Native MCP server** | Zaten dahili MCP desteği var (14 tool) |
| **a11y-snapshot** | Accessibility tree çıktısı — AI agent'lar için ideal |
| **Annotated screenshots** | Etiketli screenshot'lar — AI'ın sayfayı anlaması |
| **40+ CLI komutu** | Zengin komut seti, tek binary |
| **Proje bazlı izolasyon** | Her proje dizini kendi browser instance'ı |
| **DevExtension sistemi** | Native JS injection — genişletilebilir |
| **MIT lisans** | Tam açık kaynak, ticari kullanım serbest |

### 4.2 Browserless'ın YAPMADIĞI, cdpilot'un YAPABİLECEĞİ Şeyler

#### A) AI-Native Browser API (Birincil Farklılaşma)

Browserless geleneksel Puppeteer/Playwright proxy'si. cdpilot Cloud **AI agent'lar için tasarlanmış** bir API olabilir:

```
Browserless yaklaşımı:
  1. WebSocket bağlan
  2. Puppeteer script yaz
  3. Element bul (CSS selector)
  4. Etkileşim yap

cdpilot Cloud yaklaşımı (AI-native):
  1. REST API çağır: POST /act
  2. Doğal dil veya a11y-ref ile hedef belirt
  3. AI agent'ın anlayacağı yapılandırılmış veri al
  4. Annotated screenshot + a11y tree + sayfa durumu tek response'ta
```

**Killer feature'lar:**

| Feature | Browserless | cdpilot Cloud |
|---------|------------|---------------|
| **a11y-snapshot endpoint** | Yok | `GET /a11y` → tam erişilebilirlik ağacı |
| **Annotated screenshot** | Yok | `GET /screenshot?annotate=true` → etiketli görüntü |
| **Ref-based interaction** | Yok | `POST /click {"ref": "button[3]"}` → a11y ref ile tıklama |
| **Sayfa durumu özeti** | Yok | `GET /state` → form değerleri, aktif element, scroll konumu |
| **MCP-ready endpoint** | Yok | `wss://api/mcp` → doğrudan MCP bağlantısı |
| **Batch komutları** | Sınırlı | `POST /batch` → birden fazla komutu atomik çalıştır |

#### B) MCP-First Mimari

2026'da MCP standart haline geldi (97M+ aylık indirme, Linux Foundation'a devredildi). cdpilot zaten MCP server. Cloud versiyonu:

```
AI Agent (Claude, GPT, Gemini, yerel LLM)
    │
    ├── MCP protokolü (standart)
    │
    ▼
cdpilot Cloud MCP Gateway
    │
    ├── tools/list → 40+ browser tool
    ├── tools/call → browser_navigate, browser_a11y, browser_click_ref...
    └── Stateful session (agent bağlamını korur)
```

**Bu yaklaşım neden güçlü:**
- Browserless: Puppeteer/Playwright bilgisi gerektirir
- cdpilot Cloud: AI agent doğrudan MCP üzerinden tarayıcı kullanır, kod yazmaya gerek yok
- WebMCP (Google, Şubat 2026) standardı ile uyumlu

#### C) Lightweight & Fast

| Metrik | Browserless | cdpilot Cloud (hedef) |
|--------|------------|----------------------|
| Cold start | 2-5 saniye | <1 saniye (önceden hazır havuz) |
| Bellek/instance | 250-500MB | 90-150MB (minimal Chrome flags) |
| Bağımlılık | Node.js + onlarca paket | Python stdlib + Chrome |
| Docker image boyutu | ~1.5GB+ | <500MB (hedef) |
| İlk API çağrısına süre | 3-8 saniye | <2 saniye |

#### D) Şeffaf & Basit Fiyatlandırma

Browserless'ın unit sistemi kafa karıştırıcı. cdpilot Cloud:

```
Basit model: Dakika bazlı fiyatlandırma
- 1 dakika browser süresi = 1 kredi
- Kredi fiyatı sabit (örn: $0.005/dakika)
- Session arası bekleme ücretsiz
- Reconnect aynı session → ek ücret yok
```

### 4.3 Hedef Segment: AI Agent Geliştiricileri

Browserless'ın hedef kitlesi geniş (scraping, testing, PDF, otomasyon). cdpilot Cloud **dar ve derin** hedefler:

```
Birincil Hedef: AI Agent Geliştiricileri
├── Claude Code / MCP kullanıcıları
├── LangChain/LangGraph agent builder'ları
├── Browser-use, Stagehand framework kullanıcıları
├── CrewAI, AutoGPT ekosistemi
└── Kurumsal RPA → AI agent dönüşümcüleri

İkincil Hedef: Geliştirici Araçları
├── CI/CD screenshot/test
├── SEO analiz araçları
└── Monitoring/uptime checker'lar
```

---

## 5. cdpilot Cloud MVP Planı

### 5.1 Minimum Viable Product

**MVP kapsamı (4-6 hafta):**

```
Faz 1 — Temel Altyapı (Hafta 1-2)
├── Docker container (Chrome + cdpilot.py)
├── HTTP API gateway (session oluşturma, yönetim)
├── Session havuzu (önceden hazır browser'lar)
├── Token-based auth
└── Tek bölge (Hetzner veya Fly.io)

Faz 2 — Core API (Hafta 2-3)
├── REST endpoints:
│   ├── POST /sessions → session oluştur
│   ├── GET /sessions/:id/screenshot → screenshot
│   ├── GET /sessions/:id/screenshot?annotate=true → AI-annotated screenshot
│   ├── GET /sessions/:id/a11y → a11y tree
│   ├── POST /sessions/:id/navigate → URL git
│   ├── POST /sessions/:id/click → tıkla (CSS veya a11y ref)
│   ├── POST /sessions/:id/fill → form doldur
│   ├── POST /sessions/:id/eval → JS çalıştır
│   ├── GET /sessions/:id/content → sayfa metni
│   ├── POST /sessions/:id/batch → toplu komut
│   └── DELETE /sessions/:id → session kapat
├── WebSocket endpoint:
│   └── wss://api/sessions/:id/cdp → raw CDP proxy
└── MCP endpoint:
    └── wss://api/mcp?token=X → MCP server (tüm tool'lar)

Faz 3 — Farklılaştırıcı Özellikler (Hafta 3-4)
├── AI-ready response formatları (structured JSON)
├── a11y-snapshot + annotated screenshot combo endpoint
├── Session state persistence (agent bağlamı)
├── Rate limiting + usage tracking
└── Basit dashboard (kullanım istatistikleri)

Faz 4 — Lansman (Hafta 4-6)
├── Stripe entegrasyonu (faturalandırma)
├── docs.cdpilot.dev (API dokümantasyonu)
├── npm paketine cloud client ekleme
├── Blog yazıları + HackerNews launch
└── İlk 10 beta kullanıcı
```

### 5.2 Teknik Mimari

```
                                    ┌─────────────────┐
                                    │   cdpilot.dev    │
                                    │   (Dashboard)    │
                                    └────────┬─────────┘
                                             │
┌──────────────┐    HTTPS/WSS    ┌───────────┴──────────┐
│  AI Agent    │ ◄──────────────► │   API Gateway        │
│  (Claude,    │                  │   (Caddy/Traefik)    │
│   GPT, vb.) │                  │   ├── Auth (JWT)     │
└──────────────┘                  │   ├── Rate Limit     │
                                  │   └── Load Balance   │
                                  └───────────┬──────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                        ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
                        │  Worker 1  │   │  Worker 2  │   │  Worker N  │
                        │ ┌────────┐ │   │ ┌────────┐ │   │ ┌────────┐ │
                        │ │Chrome 1│ │   │ │Chrome 1│ │   │ │Chrome 1│ │
                        │ │Chrome 2│ │   │ │Chrome 2│ │   │ │Chrome 2│ │
                        │ │Chrome 3│ │   │ │Chrome 3│ │   │ │Chrome 3│ │
                        │ └────────┘ │   │ └────────┘ │   │ └────────┘ │
                        │ cdpilot.py │   │ cdpilot.py │   │ cdpilot.py │
                        └────────────┘   └────────────┘   └────────────┘
                              │               │               │
                              └───────────────┼───────────────┘
                                              │
                                    ┌─────────┴─────────┐
                                    │   Redis/Valkey     │
                                    │   (Session state,  │
                                    │    queue, metrics)  │
                                    └────────────────────┘
```

**Worker mimarisi:**
- Her worker = 1 Docker container
- Container başına 3-5 Chrome instance (kaynaklara göre)
- Chrome instance'lar önceden başlatılmış (warm pool)
- Session timeout → instance geri dönüşüm havuzuna

### 5.3 Altyapı Seçenekleri

| Seçenek | Avantaj | Dezavantaj | Maliyet (tahmini) |
|---------|---------|------------|-------------------|
| **Hetzner Cloud** | Ucuz, güçlü CPU, AB bölgesi | ABD bölgesi sınırlı | ~$40-80/ay başlangıç |
| **Fly.io** | Auto-scale, global dağıtım, on-demand VM | Chrome ile karmaşık | ~$50-150/ay |
| **Kendi Sunucu (10.0.0.21/24)** | Sıfır maliyet, tam kontrol | Tek nokta, ölçeklenemez | $0 (başlangıç) |
| **Coolify + Hetzner** | Self-hosted PaaS, Docker deploy | Kurulum gerekli | ~$40/ay |

**Önerim: Hibrit başlangıç**
1. **MVP (Faz 1):** Kendi sunucu (10.0.0.21) → sıfır maliyet, hızlı iterasyon
2. **Beta (Faz 2):** Hetzner CPX31 (4 vCPU, 8GB RAM) → ~$15/ay, 10-15 eşzamanlı session
3. **Ölçekleme (Faz 3):** Hetzner + Fly.io hibrit → multi-region

### 5.4 Maliyet Analizi

**Headless Chrome kaynak tüketimi:**

| Metrik | Basit sayfa | Orta karmaşık | Ağır (SPA) |
|--------|-------------|---------------|------------|
| RAM | 90-120MB | 150-250MB | 300-500MB |
| CPU | 0.1-0.3 core | 0.3-0.5 core | 0.5-1.0 core |
| Süre | 2-5 saniye | 5-15 saniye | 15-60 saniye |

**Hetzner CPX31 (4 vCPU, 8GB RAM, ~$15/ay) kapasitesi:**

```
Eşzamanlı session (orta karmaşık): ~15-20
Günlük session kapasitesi (30 sn ortalama): ~40.000-50.000
Aylık session kapasitesi: ~1.2M-1.5M

Birim maliyet:
- $15 / 1.200.000 session = $0.0000125/session
- Hedef satış fiyatı: $0.001-0.003/session (80-240x margin)
```

**Browserless ile karşılaştırma:**

| Plan | Browserless | cdpilot Cloud (hedef) |
|------|------------|----------------------|
| 1.000 session/ay | Ücretsiz | Ücretsiz |
| 20.000 session/ay | $25/ay | $10/ay |
| 180.000 session/ay | $140/ay | $50/ay |
| 500.000 session/ay | $350/ay | $100/ay |

**%50-70 daha ucuz fiyatlandırma mümkün** çünkü:
- Sıfır bağımlılık = daha az kaynak tüketimi
- Kendi altyapı = cloud provider margin'i yok
- Küçük ekip = düşük operasyonel maliyet

### 5.5 API Tasarımı

#### REST API (v1)

```
Base URL: https://api.cdpilot.dev/v1

Auth: Bearer token (header) veya ?token=X (query)

# Session Yönetimi
POST   /sessions                    → Yeni session oluştur
GET    /sessions/:id                → Session durumu
DELETE /sessions/:id                → Session kapat
GET    /sessions                    → Aktif session listesi

# Navigasyon
POST   /sessions/:id/navigate      → URL'ye git
GET    /sessions/:id/content        → Sayfa metni (text)
GET    /sessions/:id/html           → Sayfa HTML'i

# AI-Native Endpoints (FARKLILAŞTIRICI)
GET    /sessions/:id/a11y           → Accessibility tree (JSON)
GET    /sessions/:id/screenshot     → Screenshot (PNG)
GET    /sessions/:id/screenshot?annotate=true  → Etiketli screenshot
GET    /sessions/:id/state          → Sayfa durumu (form, scroll, aktif element)
POST   /sessions/:id/act            → Doğal dil veya a11y-ref ile aksiyon

# Etkileşim
POST   /sessions/:id/click         → Element tıkla (CSS veya ref)
POST   /sessions/:id/fill          → Form alanı doldur
POST   /sessions/:id/type          → Metin yaz
POST   /sessions/:id/keys          → Klavye kısayolu
POST   /sessions/:id/eval          → JavaScript çalıştır

# Toplu İşlem
POST   /sessions/:id/batch         → Birden fazla komutu sıralı çalıştır

# Utility
GET    /sessions/:id/pdf           → PDF oluştur
GET    /sessions/:id/cookies       → Cookie'leri al
POST   /sessions/:id/cookies       → Cookie ayarla
```

#### MCP Endpoint

```
wss://api.cdpilot.dev/v1/mcp?token=X

→ Standart MCP protokolü (JSON-RPC 2.0)
→ 40+ tool otomatik keşif
→ Stateful session (agent bağlamı korunur)
→ Claude Code, Cursor, VS Code uyumlu
```

#### CDP Proxy (Puppeteer/Playwright uyumluluğu)

```
wss://api.cdpilot.dev/v1/cdp?token=X

→ Raw CDP WebSocket proxy
→ Mevcut Puppeteer/Playwright scriptleri çalışır
→ Browserless'tan kolay geçiş
```

### 5.6 İlk 10 Müşteriyi Bulma Stratejisi

Joel Griffith'in kanıtlanmış yöntemini **AI-native** bağlamda uygula:

#### Hafta 1-2: Topluluk Varlığı

1. **GitHub Issues (öncelikli):**
   - `browser-use`, `stagehand`, `playwright-mcp` repo'larında soruları yanıtla
   - "Cloud'da çalıştırmak istiyorum" diyen herkese cdpilot Cloud'u öner
   - Claude Code ile MCP kullanım örnekleri paylaş

2. **Reddit:**
   - r/ClaudeAI, r/LocalLLaMA, r/webdev, r/webscraping
   - "MCP ile tarayıcı otomasyonu" konulu paylaşımlar

3. **X (Twitter):**
   - AI agent builder'ları etiketle
   - Demo GIF/video paylaş
   - #MCP #BrowserAutomation #AIAgent hashtag'leri

#### Hafta 3-4: İçerik Motoru

4. **Blog yazıları (cdpilot.dev/blog):**
   - "Browserless vs cdpilot Cloud: AI Agent'lar İçin Hangisi?"
   - "MCP ile Tarayıcı Otomasyonu: Tam Rehber"
   - "Claude Code + cdpilot Cloud: 5 Dakikada Web Agent"

5. **HackerNews Launch:**
   - "Show HN: cdpilot Cloud — AI-native browser API with MCP support"
   - Teknik detaylar, farklılaşma, ücretsiz tier vurgula

6. **Dev.to / Medium:**
   - Tutorial serisi: "Building AI Web Agents with cdpilot"

#### Hafta 5-6: Doğrudan Erişim

7. **MCP ekosistemindeki projeler:**
   - mcpmarket.com'da listeleme
   - MCP server olarak paket yayınlama
   - Anthropic'in MCP dizinine ekleme

8. **Mevcut cdpilot npm kullanıcıları:**
   - npm'deki mevcut kullanıcılara "Cloud versiyonu beta" bildirimi
   - package.json'a cloud entegrasyonu ekleme

9. **AI tool aggregator'lar:**
   - firecrawl.dev, browsermcp.io gibi listelere ekleme
   - G2, Capterra profili oluşturma

10. **Kişisel ağ:**
    - AI/ML Discord sunucuları
    - Indie Hackers topluluğu
    - Y Combinator forumu

### 5.7 Fiyatlandırma Stratejisi (Lansman)

```
FREE (Hobi/Test):
├── 2.000 session/ay (Browserless'tan 2x fazla)
├── 3 eşzamanlı tarayıcı
├── 5 dakika session limiti
├── Tek bölge
└── Topluluk desteği

DEVELOPER ($15/ay):
├── 50.000 session/ay
├── 10 eşzamanlı tarayıcı
├── 15 dakika session limiti
├── MCP endpoint
├── Annotated screenshots
├── Email desteği
└── 7 gün session log

PRO ($75/ay):
├── 300.000 session/ay
├── 30 eşzamanlı tarayıcı
├── 30 dakika session limiti
├── Tüm bölgeler
├── CDP proxy (Puppeteer uyumlu)
├── Öncelikli destek
└── 30 gün session log

SCALE ($200/ay):
├── 1.000.000 session/ay
├── 100 eşzamanlı tarayıcı
├── 60 dakika session limiti
├── Özel proxy desteği
├── SLA %99.9
├── Dedicated account
└── 90 gün session log
```

**Browserless'a göre avantaj:** Her planda %40-60 daha ucuz + AI-native özellikler dahil.

---

## 6. Rekabetçi Pozisyonlama Özeti

```
                    Geleneksel Otomasyon ◄──────────────────► AI-Native Otomasyon
                         │                                           │
            ┌────────────┤                                           ├────────────┐
            │            │                                           │            │
     Browserless    Browserbase                              cdpilot Cloud   Hyperbrowser
     (geniş hedef)  (serverless)                            (MCP-first)     (LLM dahili)
            │            │                                           │
            │   Puppeteer/Playwright proxy                   MCP + a11y + annotated
            │   Unit-based pricing                           Dakika bazlı, basit
            │   8 yıllık moat                                Sıfır bağımlılık, MIT
            │                                                AI agent odaklı
```

### cdpilot Cloud'un Konumu

**"AI Agent'lar için tasarlanmış, MCP-first browser API"**

- Browserless'tan farkı: AI-native (a11y, annotated screenshot, MCP endpoint)
- Browserbase'den farkı: Self-host seçeneği, MIT lisans, daha ucuz
- Playwright MCP'den farkı: Cloud-hosted, session yönetimi, ölçeklenebilir
- Lightpanda'dan farkı: Chrome uyumluluğu, gerçek tarayıcı davranışı

---

## 7. Risk Analizi & Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| Browserless AI-native özellikler ekler | Yüksek | Orta | Hız avantajı — 6 ay önceden piyasada ol |
| Google/Anthropic kendi browser API sunar | Orta | Yüksek | Self-host opsiyonu + özel niche |
| WebMCP standardı browser API'yı gereksiz kılar | Düşük (2+ yıl) | Yüksek | WebMCP uyumlu geçiş planı |
| Chrome kaynak tüketimi ölçeklenme engeli | Orta | Orta | Lightpanda/headless-shell alternatifleri |
| Fiyat savaşı | Orta | Orta | Altyapı maliyet avantajı, küçük ekip |

---

## 8. 90 Günlük Yol Haritası

```
Hafta 1-2: Temel Altyapı
├── [ ] Docker container (Chrome + cdpilot.py + API gateway)
├── [ ] Session havuzu (warm pool)
├── [ ] Token auth + rate limiting
├── [ ] Kendi sunucuda test ortamı
└── [ ] CI/CD pipeline

Hafta 3-4: Core API
├── [ ] REST API (session CRUD + navigasyon + etkileşim)
├── [ ] AI-native endpoint'ler (a11y, annotated screenshot, state)
├── [ ] MCP WebSocket endpoint
├── [ ] CDP proxy (Puppeteer uyumluluğu)
└── [ ] Basit kullanım dashboard'u

Hafta 5-6: Beta Lansman
├── [ ] Hetzner'a production deploy
├── [ ] Stripe entegrasyonu (Free + Developer plan)
├── [ ] docs.cdpilot.dev (API docs)
├── [ ] npm paketine cloud client ekleme
└── [ ] İlk 10 beta kullanıcı davet

Hafta 7-8: İçerik & Topluluk
├── [ ] Blog yazıları (3-5 adet)
├── [ ] HackerNews "Show HN" lansmanı
├── [ ] GitHub Issues/Reddit/X varlığı
├── [ ] MCP dizinlerine listeleme
└── [ ] Demo video + tutorial

Hafta 9-12: İterasyon
├── [ ] Kullanıcı geri bildirimleriyle iyileştirme
├── [ ] Pro plan lansmanı
├── [ ] İkinci bölge (AB)
├── [ ] Stealth/anti-detect özellikleri
└── [ ] Hedef: 50+ aktif kullanıcı, $500+ MRR
```

---

## Kaynaklar

- [Browserless Pricing](https://www.browserless.io/pricing)
- [Browserless Unit-Based Pricing Blog](https://www.browserless.io/blog/unit-based-pricing)
- [Browserless Connection URLs & Endpoints](https://docs.browserless.io/overview/connection-urls)
- [Browserless vs Browserbase](https://www.browserless.io/blog/browserless-vs-browserbase)
- [Browserless v2 Rebuild Story](https://www.browserless.io/blog/rebuilding-browserless)
- [Joel Griffith: $200 to $4M ARR Bootstrapped (SaaS Club Podcast)](https://saasclub.io/podcast/bootstrapped-saas-joel-griffith-browserless/)
- [Joel Griffith: $28K/Month Growth Story (Starter Story)](https://www.starterstory.com/headless-browser-service)
- [Browserless on Indie Hackers](https://www.indiehackers.com/interview/how-ive-grown-my-headless-browser-business-to-1-000-mo-6abb96ab8a)
- [Browserless HackerNews Discussion](https://news.ycombinator.com/item?id=39526797)
- [Browserless GitHub](https://github.com/browserless/browserless)
- [Browserless Open Source Docs](https://docs.browserless.io/enterprise/open-source)
- [Agentic Browser Landscape 2026 (NoHacks)](https://nohacks.co/blog/agentic-browser-landscape-2026)
- [Browser Automation Tools Comparison 2026 (Firecrawl)](https://www.firecrawl.dev/blog/browser-automation-tools-comparison)
- [Browser Automation MCP Servers (MCP Market)](https://mcpmarket.com/categories/browser-automation)
- [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)
- [Browserless G2 Reviews](https://www.g2.com/products/browserless-io/reviews)
- [Browserless Alternatives (G2)](https://www.g2.com/products/browserless-io/competitors/alternatives)
