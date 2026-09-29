# Plan: Eklenti API v1 ve ilk eklenti `cdpilot-jev`

[DURUM: TASLAK — Nadir onayı bekliyor] · 2026-09-28 · Kaynak: `YANITLAR-2026-09-28.md` §4-5
Kapsam: yalnız tasarım, kod yok. 0.9.4 ve Chrome for Testing bu planın dışında.

## 0. Özet

- Eklenti ayrı bir pip paketidir ve yalnız `cdpilot.plugins` entry-point grubundan bulunur
  (stdlib `importlib.metadata`, Python ≥3.10).
- **Yerleşik komutlar eklenti keşfini hiç çalıştırmaz.** Keşif yalnız şu yollarda çalışır:
  bilinmeyen komut, `plugins`, `mcp` açılışı ve isteğe bağlı karar danışması. Yerleşik komutların
  maliyeti değişmez.
- v1 kancaları: komut, MCP aracı, karar sağlayıcı. Sayfa olayı kancası v2'ye kalır.
- `cdpilot-jev` dört kararı tipli verir: sayfa durumu, öğe seçimi, alan eşleme, sonuç doğrulama.
  Sağlayıcı parametriktir: `jev`, `systemone` (yerel Laya/Kev, aynı şema), `heuristic`
  (çekirdek). cdpilot'ta LLM yok. "LLM'e bırak", kararsız sonuç (exit 3) döndürmek demektir;
  kararı çağıran ajan verir.
- **Kod yazılmadan önce ölçüm yapılır.** Sahibin 27.09 ölçümünde Jev, OpenRouter üzerinden
  medyan 583-1031 ms, p95 en çok 4,2 s verdi (`RAPOR-2026-09-27.md`). Duyurulan 70-500 ms
  bizim ağımızda görülmedi. "Daha hızlı" iddiası yalnız §3.7 kapısını geçerse yazılır.

## 1. Terim ve ilkeler

- **Eklenti (plugin):** cdpilot'a Python paketi olarak takılan genişleme.
- **Tarayıcı uzantısı:** `ext-install` ve `extensions` ile yönetilen şey. İki kavram karışmamalı.
  README'deki "Captcha Solver Plugins" başlığı "Captcha Solver Providers" olmalı.
- Çekirdek stdlib + `websockets` olarak kalır.
- Eklenti tam yetkili koddur, sandbox değildir. Belgeler bunu açıkça söyler.

## 2. Eklenti API v1

### 2.1 Keşif
- **Grup:** `cdpilot.plugins`.
  - Entry-point adı eklenti kimliğidir (`^[a-z][a-z0-9-]{1,23}$`).
  - Değer biçimi `paket.manifest:PLUGIN`.
- **cwd'den yükleme yok:** `''`, `.`, `os.getcwd()` ve cwd altındaki yollar dağıtım listesinden
  çıkarılır. PYTHONPATH'ten gelen dağıtımlar `plugins` çıktısında "env" diye işaretlenir.
- **Yorumlayıcı:** `bin/cdpilot.js` `findPython()` kullanır.
  - `plugins` komutu yorumlayıcı yolunu ve tam kurulum ipucunu basar:
    `<python> -m pip install cdpilot-jev`.
  - Homebrew Python'daki PEP 668 engeli için öneri: `CDPILOT_PYTHON=<venv>/bin/python`.

### 2.2 Sözleşme (`plugin_api = 1`)
Manifest yalnız veri taşır, üçüncü taraf paket import etmez. İşleyiciler `"mod:fn"` dizgesi
olarak verilir ve yalnız çağrılınca import edilir. Tembel yüklemenin temeli budur.

| Alan | Tip | Not |
|---|---|---|
| `plugin_api` | int | zorunlu; çekirdek `PLUGIN_API_SUPPORTED = {1}` |
| `id`, `version`, `summary` | str | `id` entry-point adıyla aynı olmalı, yoksa "bozuk" |
| `min_cdpilot` | str? | `__version__` ile karşılaştırılır |
| `commands` | {ad: {handler, async, touches_page, usage}} | `touches_page` → görsel gösterge sarmalı |
| `mcp_tools` | [{name, description, inputSchema, command, sends_page_content}] | bildirimsel |
| `decision_providers` | {ad: "mod:fabrika"} | §2.3 |
| `data_egress` | [alan adı] | `plugins` ve MCP açıklamasında gösterilir |
| `requires_env` | [ad] | eksikse durum "yapılandırılmamış", MCP'de listelenmez |

**Host API (eklentinin tek yüzeyi).** cdpilot npm ile dağıtılan bir betiktir ve `__main__` olarak
çalışır. Bu yüzden eklenti `import cdpilot` yapamaz; bütün erişimi host nesnesinden alır:
- **Bilgi:** `host.api_version`, `host.cdpilot_version`, `host.project_id`.
- **Depolama:** `host.home_dir()` (`CDPILOT_HOME/plugins/<id>`, 0700).
- **Tarayıcı:** `await host.cdp(method, params, timeout)`, `await host.eval(js)`, `host.page()`.
- **Sayfa okuma:** `await host.snapshot(budget_chars)`, `await host.candidates(intent, limit=20)`,
  `await host.form_fields()`, `await host.friction()`.
- **Eylem ve karar:** `await host.act(id, "click"|"fill", value=None)`, `host.decide(kind, state, **kw)`.
- **Hata:** `host.fail(msg, code)`.

**Uyumluluk:**
- v1 içinde yalnız ekleme yapılır; kaldırma ya da anlam değişikliği v2 demektir.
- N ve N-1 bir minor seri boyunca birlikte desteklenir.
- Uyumsuz eklenti komutu exit 2 ile ipucu verir: "cdpilot'u güncelle ya da `cdpilot-jev<X` sabitle".

### 2.3 Kanca noktaları

| Kanca | v1? | Gerekçe |
|---|---|---|
| Yeni CLI komutu | Evet | Tembel yükleme bilinmeyen komut dalında |
| Yeni MCP aracı | Evet | Bildirimsel; sunucuda eklenti kodu çalışmaz |
| Karar sağlayıcı | Evet | friction ve smart-click bu arayüze danışır, sağlayıcıya bağlanmaz |
| Sayfa olayı kancası | Hayır (v2) | cdpilot her komutta ayrı süreçtir; kanca her komutta keşif gerektirir |

**Karar arayüzü:** `decide(kind, state, params) -> {decided, value, confidence, probabilities, provider, ms}`.
- Türler: `page_state`, `pick`, `fields`, `verify`.
- Çekirdekte hazır gelen `heuristic` sağlayıcı mevcut friction, smart-click ve smart-fill
  mantığını sarar.

### 2.4 Yönlendirme, `plugins`, kapatma
- **Yerleşik komut her zaman kazanır.** Eklenti gölgeleme girişimi "çakışma" olarak listelenir.
- **Aynı ad çakışırsa:** iki eklenti aynı adı isterse kısa ad kimseye verilmez; `id:komut`
  (ör. `jev:decide`) her zaman çalışır.
- **`cdpilot plugins [--json] [--timing]`:** id, dağıtım, sürüm, konum, api, durum
  (etkin / uyumsuz / bozuk / yapılandırılmamış / kapalı / çakışma), komutlar, araçlar,
  sağlayıcılar, egress, Python yolu.
- **Aç/kapat:** `cdpilot plugins disable|enable <id>` → `CDPILOT_HOME/plugins.json`.
- **`CDPILOT_NO_PLUGINS=1`:** keşif hiç çalışmaz, eklenti komutu exit 2 verir, MCP'de eklenti
  aracı ve karar danışması olmaz.

### 2.5 Hata yalıtımı
1. Yerleşik komutlar `importlib.metadata` import etmez. Bozuk bir eklenti onları etkileyemez
   (testle kanıtlanır).
2. Her entry point ayrı `try/except (Exception, SystemExit)` içinde yüklenir. Hata olursa
   "bozuk: <ilk satır>" gösterilir.
3. İşleyici istisnası: `cdpilot: eklenti jev hata verdi: …`, exit 1. Traceback yalnız
   `CDPILOT_DEBUG=1` ile basılır.
4. MCP araç çağrısı alt süreçte ve 30 s sınırla koşar. `tools/list` eklenti başına `try` içinde kurulur.
5. Çekirdek içi danışmanın sert sınırı 1500 ms'dir (`CDPILOT_DECIDER_TIMEOUT_MS`). Hata olursa
   sezgisel sonuç değişmeden kalır.

### 2.6 Başlangıç maliyeti bütçesi

| Yol | Bütçe |
|---|---|
| Yerleşik komut | +0 (`importlib.metadata` hiç yüklenmez; medyan fark ≤2 ms) |
| Eklenti komutu çözümü | ≤40 ms p50, ~150 dağıtımlı ortamda |
| `mcp` açılışı | ≤100 ms ek |

**Ölçüm:**
- `python -X importtime` ve 30 koşuluk döngü.
- Üç ortam: temiz, şişman (~150 dağıtım), 1 ve 5 sahte eklenti.
- Rapor: `.claude/docs/eklenti-baslangic-olcumu-<tarih>.md`.
- 40 ms aşılırsa `plugins-cache.json` eklenir; ölçmeden eklenmez.

### 2.7 Güvenlik
- **Yükleme sınırları:** Yalnız kurulu dağıtımlar yüklenir. cwd filtresi, kimlik doğrulaması ve
  gölgeleme yasağı uygulanır. Host API bir yetki sınırı **değildir**.
- **MCP'de görünme:** Araç ancak eklenti etkinse, api uyumluysa ve `requires_env` sağlanmışsa
  listelenir.
  - Ad biçimi `<id>_<ad>`; `browser_` öneki çekirdeğe ayrılmıştır.
  - Açıklamanın başına veri çıkışı notu eklenir.
  - `CDPILOT_MCP_PLUGINS=0` eklenti araçlarının hepsini gizler.
  - Araç çağrısı `cdpilot <id>:<komut> --mcp-json` alt sürecine çevrilir.
- **Sırlar:** env ya da `home_dir()/config.json` (0600). Argv'den alınmaz; anahtar stdin'den okunur.
- **Tedarik zinciri:** README'de "bilinen eklentiler" listesi ve `cdpilot-*` ad taklidi uyarısı.

### 2.8 Test stratejisi
- **Sahte eklenti:** PYTHONPATH shim ile. Geçici `cdpilot_fake-0.1.dist-info/{METADATA,entry_points.txt}`
  ve `cdpilot_fake/manifest.py` pip'siz bulunur.
- **Varyantlar:** sağlam, `plugin_api=2`, import'ta hata, işleyicide hata, takılan işleyici
  (`--timeout` → 124), `go` adını isteyen, aynı adlı ikinci eklenti, import edilince işaret
  dosyası yazan manifest (tembelliğin kanıtı).
- **Kontroller:**
  - `version` ve `tabs` işaret dosyasını oluşturmaz; `-X importtime` çıktısında
    `importlib.metadata` görünmez.
  - `plugins --json` doğru çıktı verir.
  - `NO_PLUGINS` her şeyi kapatır.
  - MCP `tools/list` ve `tools/call` çalışır.
  - cwd'deki `evil.dist-info` yüklenmez.
  - Danışma, sahte CDP ile üç durumda sınanır: sabit yanıt, gecikme, istisna.
- **Gerçek pip:** CI'da tek bir işte (py3.12) venv + `pip install` ile sahte eklenti kurulur.

### 2.9 `src/cdpilot.py` bağlantı noktaları (28.09 satırları)
- 28-43: env belgeleri.
- 60: `PLUGIN_API_VERSION`.
- 15185 öncesi: yeni "Plugins (API v1)" bölümü.
- 15202-15207 ve 15345-15397: MCP.
- 18092-18131: `sync_cmds`'e `plugins` eklenir.
- 18314-18354: `_run_page_command()` çıkarılır.
- 18357-18364: bilinmeyen komut → eklenti.
- 9568-9627 ve 5898-5930: friction danışması.
- 4229-4259 ve 11985: smart-click danışması.
- `bin/cdpilot.js`: yalnız `showHelp`'e bir satır eklenir; bilinmeyen komutlar zaten Python'a gidiyor.

## 3. İlk eklenti: `cdpilot-jev`

### 3.1 Paket ve iş bölümü
- **Ayrı depo ve PyPI paketi.** Jev çağrısı stdlib `urllib` ile yapılabilir. Yine de eklenti
  olmasının nedenleri: üçüncü tarafa veri çıkışı, anahtar, gizlilik ve ayrı sürüm temposu.
- **Çekirdekte:** host API, `heuristic` sağlayıcı, danışma noktaları.
- **Eklentide:**
  - `decide` komutları ve soru setleri.
  - `jev` sağlayıcısı ve `systemone` sağlayıcısı (`CDPILOT_SYSTEMONE_URL`; veri makineden çıkmaz).
  - `jev config|status`.
- **Güven düşükse:** sonuç `{"decided":false,"reason":"low_confidence","top":[…3]}` olur ve
  exit 3 döner.

### 3.2 Gönderilen durum
JSON alanları:
- `url`: köken + yol; sorgu dizesi ve parça atılır.
- `title`, `lang`.
- `dialogs`: en çok 5.
- `headings`: h1-h3, en çok 15.
- `text`: görünür metin özeti, en çok 1.500 karakter, maskeli.
- `interactive`: en çok 60 öğe; alanlar `id`, `role`, `name`, `type`, `label`, `placeholder`,
  `disabled`, `in_dialog`, `in_viewport`, `frame`.
- `signals`: sezgisel friction sinyalleri.

Kurallar:
- **Maske:** input değerleri hiç gönderilmez; 6 ve daha uzun rakam dizileri `#`, e-postalar
  `<email>` olur; çerez ve depolama gönderilmez.
- **Boyut:** state ≤16k karakter (sert tavan 24k); soru başına ≤2k karakter; istekte ≤12 soru.
- **Kırpma sırası:** text → headings → görüş alanı dışındaki öğeler → adları kısaltma.
- **Şeffaflık:** `--dry-run` gönderilecek JSON'u basar, ağa çıkmaz.

### 3.3 Soru setleri
Kriterler İngilizce yazılır; Türkçe sayfalar ayrıca ölçülür.
- **page-state** (`choice`): ok / cookie_banner / login_wall / captcha / rate_limited / blocked /
  error_page / loading. Ek olarak `modal` noul. Sonuç friction basamaklarına eşlenir.
- **pick "<niyet>"** (`choice`):
  - Adaylar: smart-click'in ilk 12'si ile görüş alanındaki öğeler, en çok 19; ayrıca `none`.
  - `--act` yalnız eşiğin üstünde tıklar.
  - Yıkıcı hedefe (sil, çıkış, öde) asla tıklamaz.
- **fields** (`choice`): alan başına, en çok 12 alan. Seçenekler: email, password, username, ad,
  soyad, telefon, adres, … other.
- **verify "<beklenen>"** (`noul`):
  - `sonuc` ve `hata`.
  - `--since <snap-id>` ile yeni satırlar da eklenir.

### 3.4 Eşikler
- **Güven hesabı:** noul için `|p-0.5|×2`; choice için API'nin `confidence` değeri.
- **≥ τ_y** (0.90 ile başlar, görev başına ölçümle ayarlanır): karar verilir.
- **τ_o (0.60) ≤ güven < τ_y:** `decided:false` ve ilk 3 aday döner.
- **< τ_o, hata, 429/529 ya da zaman aşımı:** `heuristic` sağlayıcıya düşer. O da zayıfsa exit 3.
- **Sağlayıcı seçimi:** `--provider` ya da `CDPILOT_DECIDER`. `auto` sırası: jev → systemone → heuristic.
- **Etik çizgi değişmez:** login_wall, otp_sms ve hard_block hiçbir sağlayıcı kararıyla otonom
  işleme dönmez.

### 3.5 Gizlilik
- **Onay:** her projede ilk kullanımda bir kez istenir. Etkileşimsiz ortam için `CDPILOT_JEV_ACK=1`.
- **Metin** (README'de ve MCP açıklamasında da):
  > Sayfanın kırpılmış içeriği OpenRouter üzerinden TypeSafe'e gönderilir. Form değerleri, çerezler
  > ve sorgu dizesi gönderilmez. Veriyi makinede tutmak için `--provider systemone` (yerel Laya/Kev).
- **Anahtarsız kullanım:** Jev 22.09'dan beri yeni kayıt almıyor, bu yüzden varsayılan akış
  anahtarsız da çalışmalı (`heuristic`).

### 3.6 friction ve smart-click danışması
- **Açma:** yalnız `CDPILOT_DECIDER=<sağlayıcı>` ile. v1'de yalnız danışmadır; §3.7 geçilmeden
  davranış değişmez.
- **friction:** sezgisel sonuç `none` iken ekranı örten diyalog ya da çok kısa metin varsa, veya
  sonuç login_wall/hard_block ise (yanlış pozitif avı) tek çağrı yapılır. Sonuç JSON'a `"decider"`
  alanı olarak eklenir.
- **smart-click:** yalnız zayıf eşleşmede (skor <60) ya da ilk iki aday arasındaki fark ≤5 ise.
- **smart-fill:** etiket bulunamazsa `fields` denenir.

### 3.7 Ölçüm planı (kod öncesi kapı)
- **Veri seti:** 80 sayfa (en az 50), dondurulmuş (state JSON + ekran görüntüsü).
  - page-state (60 sayfa):

    | Tür | Sayı |
    |---|---|
    | Çerez bandı | 10 |
    | Giriş duvarı | 8 |
    | Captcha | 8 |
    | Hız sınırı (429) | 5 |
    | 404/500 | 6 |
    | Sert engel | 5 |
    | Temiz (en az 8'i Türkçe) | 18 |

  - pick: 25 sayfada 40 görev.
  - fields: 15 formda ~100 alan.
  - verify: 30 önce/sonra çifti.
- **Etiket:** Nadir + ajan. `bench/decide/set-v1.jsonl`, koşucu `kosucu.py`'den türetilir.
- **Metrikler:**
  - isabet ve güven dilimine göre isabet (<0.5 / 0.5-0.9 / >0.9)
  - τ_y'deki kapsam
  - Brier
  - p50/p95 gecikme (yalnız sağlayıcı ve uçtan uca)
  - 1.000 karar başına maliyet
- **Kıyas:** `heuristic` ve iki LLM tabanı (küçük ve orta, sıcaklık 0). Aynı ağ, 3 tekrar, n≥200.
- **Geçme koşulları (hepsi birlikte):**
  - Jev p50 ≤ 0,5 × LLM p50, ve Jev p95 ≤ LLM p95.
  - τ_y üstünde isabet: page-state ≥0,95 · pick ≥0,92 · fields ≥0,95 · verify ≥0,93.
  - τ_y'de kapsam ≥%60.
  - LLM tabanının en fazla 2 puan altında.
  - Çekirdek danışmayı açmak için ek koşul: sezgisel tabanı ≥10 puan geçmeli.
- **Kalırsa:** yalnız "isteğe bağlı sınıflandırıcı" olarak yayınlanır, hız iddiası yazılmaz.

## 4. Riskler

| Risk | Önlem |
|---|---|
| pip yanlış yorumlayıcıya kurulur / PEP 668 | `plugins` Python yolunu ve tam komutu basar; venv + `CDPILOT_PYTHON` |
| Jev ölçümde duyurulandan yavaş (medyan 0,6-1,0 s) | §3.7 kapısı; yerel `systemone` (Laya medyan 22-128 ms) |
| Jev kaydı kapalı | `heuristic` + `systemone` ile anahtarsız değer |
| Sayfa içeriği üçüncü tarafa gider | kırpma, maske, `--dry-run`, onay, MCP notu |
| Erken yanlış soyutlama | v1 dar tutulur, yalnız ekleme, N-1 desteği |
| "Eklenti" ile "uzantı" karışır | §1 terim kuralı |
| Kötü niyetli `cdpilot-*` paketi | açık kurulum, cwd filtresi, konum gösterimi, bilinen liste |
| Danışma `go`'yu yavaşlatır | varsayılan kapalı, 1,5 s tavan, tek çağrı |

## 5. Nadir'e açık kararlar (öneriler parantezde; Nadir aksini demezse öneri uygulanır)
1. `decide` eklentide mi, çekirdekte (`heuristic` ile) mi? (Öneri: eklentide.)
2. MCP'de eklenti araçları, anahtar varken varsayılan açık mı? (Öneri: evet.)
3. `cdpilot plugins install <ad>` v1'e girsin mi? (Öneri: hayır, v1.1.)
4. Kriter dili? (Öneri: İngilizce.)
5. LLM tabanı modelleri ve ölçüm bütçesi? (Öneri: ~5 $.)
6. `cdpilot-jev` ayrı depo mu? (Öneri: evet.)
7. Ölçüm geçerse danışma otonom davranışı değiştirebilsin mi? (Öneri: hayır, önce danışma.)

## 6. Fazlı teslim

| Faz | İş | Efor | Bağımlılık |
|---|---|---|---|
| F1 | keşif, manifest, `plugins`, `NO_PLUGINS`, yönlendirme, host API, sahte eklenti testleri, başlangıç ölçümü | 2-3 gün | — |
| F2 | karar sağlayıcı kaydı + `heuristic` + MCP araçları | 1-1,5 gün | F1 |
| F3 | ölçüm seti + koşucu + kıyas raporu — **KAPI** | 2-3 gün | F1 ile paralel |
| F4 | `cdpilot-jev`: 4 `decide`, sağlayıcılar, `--dry-run`, onay | 2-3 gün | F2, F3 |
| F5 | friction ve smart-click danışması | 1-1,5 gün | F3 geçmeli |
| F6 | README, site, iddia kapısı, PyPI, bilinen eklentiler, sözleşme | 0,5-1 gün | F4 |

Toplam ~9-13 iş günü. F3 kalırsa F5 atlanır, F4 iddiasız çıkar.
