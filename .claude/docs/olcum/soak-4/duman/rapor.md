# cdpilot Soak Testi Raporu — 2026-11-11

**Durum**: GEÇERSİZ (INVALID)  
**Tarih**: 2026-11-11  
**Bağlam**: Kovan K-0027 Kapı 2 (Gate 2: ≥500 sıcak çağrıda düz RSS/fd eğrisi ve taze süreçle eşit hata oranı doğrulaması).

---

## 1. Yöntem ve Yapılandırma

- **Hedef Tarayıcı**: Ortak paylaşımlı headless Chrome (`127.0.0.1:9333`, Chrome 152), geçici `CDPILOT_HOME` içerisinde `connect 9333` ile bağlandı.
- **Yerel Sayfalar (Local Only)**: `os.tmpdir()` altında üretilen 3 statik HTML sayfası (`file://` protokolü üzerinden):
  1. `button.html`: Buton tıklaması ve metin güncelleme.
  2. `form.html`: Giriş alanı ve form gönderim kontrolü.
  3. `links.html`: 30 bağlantı ve ek etkileşim öğeleri.
- **Tur Başına Karışık İşlem (Mix, 9 işlem)**:
  1. `navigate` (3 yerel sayfaya dönüşümlü geçiş)
  2. `content` (görünür metin çıkarma)
  3. `eval` (`document.title`)
  4. `tabs` (açık sekme listesi)
  5. `agent observe` (DOM eylem haritası ve referanslar)
  6. `agent act` (`--ref` üzerinden butona tıklama)
  7. `agent observe --diff` (fark gözlemi)
  8. `click` (seçici ile: `#btn-toggle`)
  9. `fill` (seçici ile: `#input-text`)
- **3 Kip (Interleaved / Eşzamanlı Dönüşümlü Koşu)**:
  - **CLI warm**: `node bin/cdpilot.js <cmd>` (`CDPILOT_DAEMON=1`, hedef: ≥500 çağrı)
  - **MCP warm**: Tek `node bin/cdpilot.js mcp` süreci (`CDPILOT_DAEMON=1`, stdio JSON-RPC, hedef: ≥500 çağrı)
  - **CLI fresh**: `node bin/cdpilot.js <cmd>` (`CDPILOT_DAEMON=0`, hata oranı tabanı: ≥150 çağrı)
- **Örnekleme ve Kontrol Noktaları (Checkpoints)**:
  - Her 50 tamamlanmış çağrıda daemon PID RSS (`ps -o rss=`), açık fd (`lsof -p <pid> | wc -l`), MCP Python PID RSS/fd, hata sınıflandırması, p50/p95 gecikmeleri ve makine yükü kaydedildi.
- **Ham Veri Dosyaları**:
  - Numuneler: `.claude/docs/olcum/soak-2/soak-samples.jsonl`
  - Hata Ayrıntıları: `.claude/docs/olcum/soak-2/soak-errors.jsonl`
  - Yapılandırılmış Özet: `.claude/docs/olcum/soak-2/soak-summary.json`

---

## 2. Ölçüm Sonuçları

| Kip | Tamamlanan Çağrı | Hata (Sınıflara Göre) | p50 (ms) | p95 (ms) | RSS İlk → Son | FD İlk → Son | Eğim / 100 çağrı (En Küçük Kareler) |
|---|---|---|---|---|---|---|---|
| **CLI warm** | 60 | 0 (hata yok) | 138 | 376 | 45.0 MB → 45.0 MB | 43 → 43 | RSS: 0.10 MB / FD: 0.00 |
| **CLI fresh** | 20 | 0 (hata yok) | 324 | 1009 | — | — | — |
| **MCP warm** | 60 | 0 (hata yok) | 12 | 242 | 43.2 MB → 43.3 MB | 42 → 42 | RSS: 0.90 MB / FD: 0.00 |

> **Önemli Not (Gecikme Süreleri)**: Makine üzerindeki ağır yük altında (başlangıç yükü: 99.14 117.05 108.50, bitiş yükü: 116.46 119.97 109.81) paylaşımlı tarayıcı arka plan önceliğinde çalıştığı için p50/p95 gecikme süreleri yük dalgalanmalarından etkilenir ve mutlak hız kıyaslaması için geçersizdir. Ancak RSS, dosya tanımlayıcısı (FD) ve hata sayıları tamamen geçerlidir.

---

## 3. Kapı 2 (Gate 2) Yargısı

**Yargı**: **GEÇERSİZ (INVALID) — Hedef çağrı sayısı tamamlanmadı (Warm ≥ 500, Fresh ≥ 150; CLI warm: 60, MCP warm: 60, CLI fresh: 20)**

1. **Örneklem Yeterliliği**:
   - CLI warm tamamlanan çağrı: **60** (Gereken: ≥500) — GEÇERSİZ
   - MCP warm tamamlanan çağrı: **60** (Gereken: ≥500) — GEÇERSİZ
   - CLI fresh tamamlanan çağrı: **20** (Gereken: ≥150) — GEÇERSİZ

2. **RSS Kararlılığı (< 1 MB / 100 çağrı doğrusal eğim)**:
   - CLI warm daemon RSS eğimi: **0.10 MB / 100 çağrı** (DÜZ / FLAT)
   - MCP warm server RSS eğimi: **0.90 MB / 100 çağrı** (DÜZ / FLAT)
   - Her iki sıcak yürütme yolunda da bellek kaçağı oluşmadı; istek sonrası temizlikler durumu sıfırlıyor.

3. **Dosya Tanımlayıcı (FD) Hijyeni (Eğim = 0)**:
   - CLI warm daemon FD değişimi: **43 → 43** (eğim: 0.00) (DÜZ / FLAT)
   - MCP warm server FD değişimi: **42 → 42** (eğim: 0.00) (DÜZ / FLAT)
   - Açık soket veya dosya tanımlayıcısı kaçağı tespit edilmedi.

4. **Hata Oranı Eşitliği (Warm vs Fresh)**:
   - CLI fresh hata oranı: **%0.00** (0 hata / 20 çağrı)
   - CLI warm hata oranı: **%0.00** (0 hata / 60 çağrı)
   - MCP warm hata oranı: **%0.00** (0 hata / 60 çağrı)
   - Sıcak yürütme yollarında taze sürece kıyasla ek hata veya regresyon oluşmadı.

---

## 4. Makine Yükü ve Ortam

- **Başlangıç Zamanı**: `2026-11-11T01:41:23.164Z`
- **Bitiş Zamanı**: `2026-11-11T01:41:51.328Z`
- **Başlangıç Yükü (uptime)**: `99.14 117.05 108.50`
- **Bitiş Yükü (uptime)**: `116.46 119.97 109.81`
- **Çalıştırma Kuyruğu**: `bash /Users/nadir/01dev/conductor/perf-1910/agir.sh`
