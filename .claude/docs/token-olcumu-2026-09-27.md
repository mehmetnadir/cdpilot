# cdpilot "500x fewer tokens than screenshots" — ölçüm (2026-09-27)

Amaç: hero/pricing sayfalarındaki ve README'deki "a11y-snapshot: 500x fewer
tokens than screenshots" iddiasını savunmadan/çürütmeden, doğrudan ölçmek.
Sonuç sitenin ve README'nin ne yazması gerektiğini belirler.

## Kurulum (yöntem)

- Depo: `/Users/nadir/01dev/cdpilot` (çalışma kopyası değiştirilmedi).
- İzole headless Brave: `CDPILOT_HOME`, `CDPILOT_PROFILE` scratchpad altında,
  `CDP_PORT=9337`, `CHROME_HEADLESS=1` (env override — kalıcı config'e
  dokunmadı), `CDPILOT_PYTHON=/usr/local/bin/python3.13`. `bin/cdpilot.js`
  hem `CDP_PORT` hem `CDPILOT_PROFILE` set edilince "tam manuel override"
  moduna geçiyor ve gerçek `~/.cdpilot/registry.json`'a hiç dokunmuyor
  (`bin/cdpilot.js:283-286`). Kullanıcının gerçek tarayıcısı/9222 portu
  hiç kullanılmadı. İş bitince `pkill -f "user-data-dir=<scratch-profile>"`
  ile yalnız bu izole Brave süreçleri kapatıldı.
- 4 gerçek sayfa: Hacker News anasayfa, Wikipedia "Chrome DevTools Protocol"
  maddesi, GitHub `mehmetnadir/cdpilot` repo sayfası, saucedemo.com (form
  ağırlıklı e-ticaret demo login sayfası).
- Her sayfada sırayla: `cdpilot go <url>` → `cdpilot a11y-snapshot` →
  `cdpilot describe` → `cdpilot shot <path>` → `cdpilot html`. Varsayılan
  ayarlarla (hiçbir flag zorlanmadı) — kullanıcının gerçekte alacağı çıktı.
- Token tahmini: `tiktoken` kurulu bulundu (`o200k_base` — GPT-4o/GPT-5
  ailesinin gerçek tokenizer'ı, `/usr/local/bin/python3` üzerinde). Metin
  çıktıları (a11y-snapshot, describe, html) bu tokenizer ile sayıldı;
  ayrıca char/4 kaba tahmini de not düşüldü. **Claude'un kendi tokenizer'ı
  herkese açık değil** — bu yüzden Claude tarafı için metin token sayısı
  yaklaşık (o200k_base ile char-yoğunluğu benzer diller için makul bir
  proxy), görsel (screenshot) token sayısı ise Claude'un DOKÜMANTE EDİLMİŞ
  patch formülüyle **kesin**.
- Ekran görüntüsü boyutu: `cdpilot shot`'ın hiçbir `--window-size` flag'i
  yok; headless Brave varsayılan viewport'u **756×419 px** çıktı (PNG
  header'ından ölçüldü, 4 sayfada da aynı).

## Formül kaynakları (2026-09-27 itibarıyla doğrulandı, canlı fetch)

**Claude (Anthropic) — güncel resmi formül, `docs.claude.com/.../vision`
(redirect: `platform.claude.com/docs/en/build-with-claude/vision`):**
Claude görüntüyü 28×28 pikselik "patch" (visual token) birimleriyle görür:
`tokens = ceil(width/28) × ceil(height/28)`. Resize/cap kuralı: standart
katman modeller için uzun kenar ≤1568px ve azami 1568 visual token; Claude
4.7+ "high-resolution" katmanda uzun kenar ≤2576px ve azami 4784 visual
token — görüntü bu sınırları aşarsa önce oranı koruyarak küçültülüyor.
**Not:** görevde verilen "≈ genişlik×yükseklik/750, uzun kenar ~1568px"
formülü ESKİ/kaba bir yaklaşımdı — resmi sayfa artık bu 28px-patch kuralını
veriyor (muhtemelen dokümantasyon 2026 içinde güncellenmiş). Doğru kaynak
budur.

**OpenAI GPT-4o (high detail) — `developers.openai.com/api/docs/guides/images`
+ topluluk doğrulaması:** 2048×2048 kutusuna sığdır (yalnız küçültme, asla
büyütme) → kısa kenar 768px'i AŞIYORSA 768'e küçült (kısa kenar zaten
≤768 ise dokunma) → 512×512'lik karo sayısı `n` = `ceil(w/512)×ceil(h/512)`
→ `tokens = 85 + 170×n`.

## Sayfa başına tablo

Ekran görüntüsü tüm sayfalarda **756×419 px** (varsayılan headless viewport,
hiç resize tetiklenmedi — hem Claude standart/high-res hem GPT-4o kuralında
kısa kenar zaten sınırın altında):
- Claude görsel token: `ceil(756/28)×ceil(419/28) = 27×15 = 405` (standart
  ve high-res katmanda AYNI, resize tetiklenmedi)
- GPT-4o high-detail: 2 karo (`ceil(756/512)=2, ceil(419/512)=1`) →
  `85 + 170×2 = 425`

| Sayfa | a11y-snapshot (char / o200k tok / char÷4) | describe (char / o200k tok) | HTML (char / o200k tok) | screenshot px | screenshot tok (Claude / GPT-4o) |
|---|---|---|---|---|---|
| news.ycombinator.com | 24 352 / **8 182** / 6 088 | 26 569 / **8 848** | 34 573 / **11 718** | 756×419 | 405 / 425 |
| wikipedia.org (CDP maddesi) | 4 878 / **1 380** / 1 220 | 6 540 / **1 746** | 193 294 / **58 022** | 756×419 | 405 / 425 |
| github.com/mehmetnadir/cdpilot | 24 459 / **8 022** / 6 115 | 26 937 / **8 666** | 712 839 / **274 013** | 756×419 | 405 / 425 |
| saucedemo.com (login formu) | 182 / **58** / 46 | 555 / **155** | 2 731 / **716** | 756×419 | 405 / 425 |

## Oranlar

**screenshot(Claude) ÷ a11y-snapshot** (iddianın yönü — 1'in altı = a11y
DAHA PAHALI, yani screenshot ucuz kalıyor):

| Sayfa | screenshot/a11y oranı | Yorum |
|---|---|---|
| Hacker News | **0.049×** | a11y-snapshot ~20.2× DAHA PAHALI (756×419'luk küçük screenshot'tan) |
| Wikipedia | **0.29×** | a11y-snapshot ~3.4× daha pahalı |
| GitHub repo | **0.050×** | a11y-snapshot ~19.8× daha pahalı |
| saucedemo (form) | **6.98×** | a11y-snapshot ~7× DAHA UCUZ (tek sayfada iddia yönünde) |

**a11y-snapshot ÷ ham HTML** (a11y'nin gerçekten kazandığı karşılaştırma —
aynı "sayfanın yapısal verisi" iki farklı temsilde):

| Sayfa | HTML/a11y oranı |
|---|---|
| Hacker News | 1.4× |
| Wikipedia | **42.0×** |
| GitHub repo | 34.2× |
| saucedemo | 12.3× |

Ortalama ~22.5×, en iyi durumda 42×. **500×'e hiçbir karşılaştırmada
ulaşılmadı** — ne screenshot'a karşı (ki 3/4 sayfada TERSİ çıktı: a11y daha
pahalı), ne ham HTML'e karşı (en fazla ~42×).

## "500x" nereden geliyor?

`docs/hackernews-post.md` içinde (README/site'daki kısa "500x fewer tokens
than screenshots" cümlesinden FARKLI, çok daha spesifik bir bağlamda):

> "`cdpilot describe` ... A screenshot-describe round-trip goes from ~250k
> tokens (Computer Use style) to ~500 tokens."

Bu, TEK BİR `a11y-snapshot` çağrısı ile TEK BİR ekran görüntüsünü
karşılaştırmıyor — bir **Computer-Use tarzı çok turlu ajan döngüsünün
toplam token maliyetini** (her turda konuşma geçmişine yeniden eklenen
screenshot'lar birikerek ~250 000 tokene ulaşıyor), cdpilot'un TEK
`describe` çağrısıyla (~500 token, basit bir sayfada — ölçümümüzde
saucedemo describe çıktısı 155 token, HN/GitHub/Wikipedia ise 1 746–8 848
token) karşılaştırıyor. **250 000 ÷ 500 = tam olarak 500** — "500x" rakamının
kökeni büyük olasılıkla budur, ama bu round-trip/çoklu-tur senaryosu ile
hero/pricing sayfasındaki çıplak "a11y-snapshot 500x fewer tokens than
screenshots" cümlesi (tek çağrı vs tek çağrı gibi okunuyor) FARKLI şeyler
ölçüyor. Site/README bu bağlamı taşımıyor; okuyucu "bir screenshot yerine
bir a11y-snapshot alırsam 500× tasarruf ederim" diye okur — ki bizim 4
sayfalık doğrudan ölçümümüz bunu desteklemiyor (3/4 sayfada TERSİ yönde).

## Önemli çekince

Screenshot'un küçüklüğü (756×419, cdpilot'un kendi varsayılanı) karşılaştırmayı
screenshot lehine çarpıtıyor olabilir — gerçek 1920×1080 bir ekran görüntüsü
Claude'da ~1560–2691, GPT-4o'da ~1105 token tutar (resmi tablo/formülle).
Bu durumda bile a11y-snapshot HN/GitHub'da hâlâ a11y daha pahalı ya da
aynı mertebede kalıyor (8182 vs 1560–2691 → a11y hâlâ ~3-5× daha pahalı);
yalnız Wikipedia ve saucedemo'da a11y ucuzluyor. Yani viewport büyütülse
bile 500× hiçbir sayfada elde edilmiyor.

## Öneri — sitede dürüstçe ne yazılabilir

Ölçülen en düşük–en yüksek aralık kullanılarak: **"a11y-snapshot, sayfanın
ham HTML'ine kıyasla tipik olarak 1–42× daha az token kullanır (form ağırlıklı
sayfalarda ekran görüntüsüne kıyasla da ~7× daha az olabilir, ancak
içerik/link ağırlıklı sayfalarda ekran görüntüsünden daha PAHALI olabilir);
'500x fewer tokens than screenshots' iddiası çok turlu bir Computer-Use
ajan döngüsünün toplam maliyetine (~250k token) karşı tek bir `describe`
çağrısının (~500 token, basit sayfalarda) karşılaştırmasından geliyor ve
tek-çağrı a11y-snapshot-vs-screenshot karşılaştırmasını temsil etmiyor —
bu iddia ya kaldırılmalı ya da bağlamıyla (çok turlu ajan döngüsü) birlikte
yeniden yazılmalı."**

## Ham veri

`/Users/nadir/01dev/cdpilot/.claude/docs/token-olcumu-ham/` — her sayfa için
`*-a11y.txt`, `*-describe.txt`, `*-html.txt` (ham CLI çıktıları) +
`shots/*.png` (756×419 gerçek ekran görüntüleri) + `token_counts.json`
(karakter/tiktoken/char-÷4 tam sayılar).
