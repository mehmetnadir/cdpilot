# CDP Tabanlı E2E Test Runner — Öneri

> **Tarih:** 2026-03-27
> **Öneren:** ruu·ad geliştirme ekibi
> **Durum:** Öneri / Değerlendirme

---

## Problem

Mevcut E2E test araçları (Playwright, Cypress) şu sorunları yaşıyor:

| Sorun | Etki |
|-------|------|
| Yavaş (her test için tarayıcı açma/kapama) | CI süresi 5-10x artıyor |
| CSS selector bazlı → kırılgan | UI değişince testler patlıyor |
| Bakım maliyeti yüksek | Her sprint test güncelleme gerekiyor |
| Ayrı framework/config | Projede 2 test sistemi yönetme |
| Ağır dependency'ler | node_modules +200MB |

## Öneri: cdpilot'a Test Runner Katmanı

cdpilot zaten CDP üzerinden tam tarayıcı kontrolü sağlıyor. Üzerine bir
assertion + test runner katmanı eklenerek hafif, hızlı, gerçekçi bir
E2E test framework'ü oluşturulabilir.

### Mimari

```
cdpilot (mevcut)
├── go, click, fill, eval, shot, content  (navigasyon + etkileşim)
│
├── TEST KATMANI (yeni)
│   ├── assert-text <selector> "beklenen metin"
│   ├── assert-visible <selector>
│   ├── assert-url <pattern>
│   ├── assert-count <selector> <sayı>
│   ├── assert-value <selector> "değer"
│   ├── assert-screenshot <baseline.png>  (görsel regresyon)
│   │
│   ├── test-file <test.cdp>  (test dosyası çalıştır)
│   ├── test-dir <tests/>     (dizindeki tüm testleri çalıştır)
│   └── test-report           (sonuç raporu)
│
└── FIXTURE KATMANI (yeni)
    ├── before-each (URL'ye git, login ol)
    ├── after-each (screenshot al, temizle)
    └── seed-data (test verisi oluştur)
```

### Test Dosyası Formatı (.cdp)

```bash
# login.test.cdp
@name "Kullanıcı girişi"
@before go https://ruu.ad/auth/login

fill input[type=email] admin@ruu.ad
fill input[type=password] Ruuad2026
click button[type=submit]
wait .sidebar 5

assert-url /dashboard
assert-visible .sidebar
assert-text h1 "Dashboard"
shot login-success.png
```

### Avantajlar

| Özellik | Playwright | cdpilot test |
|---------|-----------|--------------|
| Tarayıcı başlatma | Her test için | 1 kez (mevcut oturum) |
| Hız | ~2-5sn/test | ~0.3-1sn/test |
| Config | playwright.config.ts | Yok (zero-config) |
| Dependency | +200MB | 0 (zaten kurulu) |
| Öğrenme eğrisi | Orta | Düşük (CLI komutları) |
| Görsel regresyon | Eklenti gerekir | Built-in (screenshot diff) |
| CI entegrasyon | Özel setup | `cdpilot test-dir tests/` |
| Gerçekçilik | %100 | %95+ (aynı CDP) |

### Uygulama Planı

1. **Faz 1:** `assert-*` komutları ekle (5-6 assertion)
2. **Faz 2:** `.cdp` test dosyası parser'ı
3. **Faz 3:** Test runner (paralel, rapor, CI çıktısı)
4. **Faz 4:** Fixture sistemi (before/after, seed data)
5. **Faz 5:** Görsel regresyon (screenshot baseline karşılaştırma)

### Potansiyel Kullanıcılar

- ruu·ad (ilk pilot proje)
- Tüm 01dev projeleri
- Açık kaynak topluluk (cdpilot zaten açık kaynak)

### Karar Gereksinimi

Bu öneriyi değerlendirip cdpilot yol haritasına eklemek veya reddetmek
proje yöneticisinin kararıdır. Kabul edilirse Faz 1 ile başlanabilir.

---

Son Güncelleme: 2026-03-27
