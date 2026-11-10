# Jüri kapısı — sürüm ve tasarım kararları (10.11.2026)

Nadir 10.11: *"benden onay almana gerek yok. bağımsız jürimiz vardı sanırım, o onaylıyorsa hiç bekleme ve hep
devam et."* (Kovan D-0040). Bu belge jürinin üyelerini, girdisini, ölçütlerini ve karar kuralını sabitler.
Jüri Nadir'in onay kutusunun yerine geçer. Gate'lerin (test, CI, güvenlik) yerine GEÇMEZ.

## 1. Ne zaman

| Karar | Jüri | Nadir |
|---|---|---|
| npm sürümü, GitHub release, MCP Registry yayını | ✅ | — |
| Varsayılan davranış değişikliği (`go` sessizlik penceresi, daemon varsayılan) | ✅ | — |
| PRD açık soruları (canlı tuval §8 gibi) | ✅ | — |
| Credential (srv21 `claude-oauth-token`, API anahtarı) | — | ✅ |
| Geri alınamaz silme, para, hesap ayarı | — | ✅ |

## 2. Üyeler

`agy-filo run <isler.json> --es 3`, her iş `kip: "oku"` (hiçbir şey yazmaz):

| Üye | Rol | Model (10.11 `agy-filo roller`) |
|---|---|---|
| J1 | `yargi` | claude-opus-5-5-high → sonnet-5-5-high → gemini-3.8-flash-high |
| J2 | `review` | claude-sonnet-5-5-high → opus-5-5-high → gemini-3.8-flash-high |
| J3 | `ikinci` | gpt-oss-120b-medium → gemini-3.8-flash-high |

Üç üye aynı dosyayı alır, birbirini görmez. Jüri üretmez, düzeltmez; puanlar ve engel yazar.

## 3. Girdi (dossier) — eksikse jüri koşmaz

1. CHANGELOG `[Unreleased]` metni ve sürüm numarası adayı.
2. `git log v<önceki>..HEAD` ve kod diff'i (`src`, `bin`, `test`, `package.json`) dosya olarak.
3. Test tutanağı kimliği ve durumu (`test-tutanak dogrula --id` çıktısı), CI koşu bağlantıları ve sonuçları.
4. T0 güvenlik smoke çıktısı (`guvenlik-smoke.sh <proje> --strict`).
5. T1 diff güvenlik incelemesi (agy-filo `review`, aynı koşuda ayrı iş; jüri dosyasına özeti girer ya da
   jüri T1 sonucunu beklemeden koşar ve şef T1'i ayrı kapı olarak uygular).
6. Bilinen açık noktalar (şefin yazdığı: ör. Windows'ta MCP taze süreç, Almanca enjeksiyon kaçağı).

## 4. Ölçütler (1–5)

| # | Ölçüt | 5 | 1 |
|---|---|---|---|
| 1 | Doğruluk | CHANGELOG'un her maddesi diff'te var, sayılar ölçüm belgesine dayanır, abartı yok | Maddede olmayan özellik ya da ölçülmemiş sayı |
| 2 | Kanıt | Tutanak GEÇERLİ, CI yeşil, yeni özelliğin testi diff'te | Test yok ya da "testler geçti" cümlesi kimliksiz |
| 3 | Güvenlik | T0 temiz, T1 yüksek bulgu yok, yeni yüzey (soket, süreç içi çalıştırma, dosya yazımı, sır maskesi) gerekçeli | Sır sızıntısı ya da doğrulanmış yetki/enjeksiyon açığı |
| 4 | Geriye uyumluluk | Varsayılan davranış aynı ya da değişiklik CHANGELOG `Changed`te; yeni yol opt-in | Sessiz davranış değişikliği |
| 5 | Belge ve tutarlılık | README, help metni, CHANGELOG, sürüm dizgileri (package/server/manifest/plugin/`__version__`) aynı şeyi söyler | Çelişen belge ya da eski sürüm dizgisi |

## 5. Çıktı (her üye tek JSON)

```json
{"uye": "J1", "model": "…", "puan": {"dogruluk": 5, "kanit": 5, "guvenlik": 4, "uyum": 5, "belge": 4},
 "karar": "YAYINLA | DUZELT_SONRA | BEKLET",
 "engeller": [{"dosya": "src/cdpilot.py", "satir": 123, "ne": "…", "neden_engel": "…"}],
 "notlar": ["…"]}
```

`engeller` yalnız yayını durduracak maddeleri alır; iyileştirme önerisi `notlar`a gider.

## 6. Karar kuralı (şef uygular)

| Sonuç | Eylem |
|---|---|
| 3/3 YAYINLA, ya da 2/3 YAYINLA ve hiçbir üyede engel yok | Beklemeden yayın |
| En az 1 DÜZELT_SONRA | Engelleri şef doğrular; doğru olanları kapatır, jüri yalnız o maddeler için yeniden koşar (en çok 2 tur) |
| 2+ BEKLET | Yayın durur; gerekçe devir notuna ve Kovan kararına yazılır. Nadir'e soru değil, kayıt. |
| İki üye arasında bir ölçütte ≥ 1,5 puan fark | Çoğunluk geçerli; karşı görüş devir notuna girer |
| Üye düştü (kota, 503) | Yedek modelle aynı rol yeniden koşar; 2 üyeyle karar verilmez |

Jüri bulgusu kanıt değildir: şef her engeli dosya/satırda doğrular ([[agy-dil-jurisi-rol-secimi]]: Gemini
rolünün 45 bulgusundan 0'ı doğru çıkmıştı). T1 yüksek bulgusu jüri YAYINLA dese de yayını durdurur.

## 7. Ölçüm

`~/.claude/canavar/agy-filo/<zaman>/ozet.json` (üye başına token ve süre) · Kovan `kovan karar` satırı
(jüri sonucu + puan tablosu) · devir notu (karşı görüşler) · haftalık: jüri sayısı, DÜZELT oranı, şefin
reddettiği engel oranı (hedef: yanlış engel ≤ %25).

## 8. Tasarım kararları (aynı jüri, başka çıktı)

"Bekleyen Nadir kararları" listesindeki tasarım soruları da bu jüriye gider. Dosya: karar başına seçenekler (A/B/C),
kanıt belgeleri (yol), şefin önerisi ve gerekçesi. Her üye karar başına tek JSON satırı yazar:
`{"karar_id": "D1", "secim": "B", "guven": 1-5, "gerekce": "≤ 3 cümle", "riskler": ["…"], "kosul": "varsa uygulama şartı"}`.
Kural: 3/3 aynı seçim → hemen uygulanır · 2/1 → çoğunluk uygulanır, karşı görüş devir notuna · 3 ayrı seçim → şef önerisi
uygulanır, üç görüş devir notuna · bir üye "koşul" yazdıysa koşul şefin uygulama planına girer. Jüri soruyu Nadir'e geri
gönderemez; "bilgi yetersiz" diyorsa hangi ölçümün eksik olduğunu yazar, şef ölçer, jüri yeniden koşar.
