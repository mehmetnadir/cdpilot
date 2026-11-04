# cdpilot 10 adımlık ajan görevi — token taban çizgisi (24.10.2026)

Sürüm: cdpilot 0.9.4. Tokenizer: tiktoken `o200k_base` (arm64 venv). Görsel: Claude 28px patch formülü.
Claude'un kendi metin tokenizer'ı kapalıdır. Metin sayıları bu yüzden yakın tahmindir (proxy).

## Özet

| Kalem | Token | Not |
|---|---|---|
| A) 10 adım çıktı toplamı | **1 308** | 4 669 karakter |
| Şema yükü (1 kez, 45 araç) | **5 769** | tools/list dizisi, o200k |
| B) Şema × 10 istek | **57 690** | her şeyi yükleyen istemci |
| C) Claude Code tarzı | **806** | 45 ad (169) + 5 araç şeması (637) |
| Senaryo 1 = A + B | **58 998** | hedef < 30 K: AŞILDI (1,97×) |
| Senaryo 2 = A + C | **2 114** | hedef < 30 K: GEÇTİ |

## Yöntem

- Ortak tarayıcı: `ortak-tarayici port` → 9333. `cdpilot connect 9333`. `context create` ile yalıtılmış bağlam.
- `CDPILOT_HOME` scratchpad altında. Gerçek `~/.cdpilot` kaydına dokunulmadı.
- `CDPILOT_PYTHON=/opt/homebrew/bin/python3` (arm64). node arm64 (nvm).
- Yeni tarayıcı başlatılmadı. Port 9222 ve 3000 kullanılmadı. Kaynak kod değişmedi, commit yok.
- Adım başına stdout+stderr dosyaya yazıldı, karakter ve token sayıldı.
- CLI çıktısı MCP araç çıktısının vekilidir. MCP sarmalayıcısı (JSON `content` zarfı) ayrıca ölçülmedi: **ölçülmedi**.
- Bağlam kapatıldı: `cdpilot context close 5A4B277A...`. Bağlam sayısı 0.

## Ölçüm 1 — şema yükü

| Metrik | Değer |
|---|---|
| Araç sayısı | 45 |
| `tools/list` yanıt satırı (JSON-RPC zarfı dahil) | 6 589 token |
| `tools` dizisi (kompakt JSON) | 5 769 token, 26 809 karakter |
| Araç başına toplam (ayrı ayrı) | 5 776 token |
| Yalnız name + description | 3 520 token |
| Yalnız adlar (45) | 125 token (satır ayraçlı liste: 169) |
| Şema payı (inputSchema vb.) | 5 776 − 3 520 = 2 256 token |

En büyük 10 araç (name + description + şema):

| # | Araç | Token | Yalnız name+desc |
|---|---|---|---|
| 1 | browser_watch_start | 297 | 110 |
| 2 | browser_watch_query | 280 | 118 |
| 3 | browser_log | 232 | 171 |
| 4 | browser_press_hold | 220 | 182 |
| 5 | browser_click | 209 | 144 |
| 6 | browser_captcha_solve | 200 | 148 |
| 7 | browser_mode | 198 | 157 |
| 8 | browser_connect | 191 | 149 |
| 9 | browser_screenshot | 183 | 64 |
| 10 | browser_friction | 177 | 166 |

Tam 45 satırlık tablo: `token-taban-ham/mcp-token-tablo.json`.

## Ölçüm 2 — 10 adım (saucedemo.com, standard_user)

| # | Komut | Karakter | Token (o200k) |
|---|---|---|---|
| 1 | go https://www.saucedemo.com/ | 162 | 38 |
| 2 | describe (login) | 555 | 155 |
| 3 | fill '#user-name' | 30 | 7 |
| 4 | fill '#password' | 29 | 8 |
| 5 | click '#login-button' | 16 | 4 |
| 6 | describe (inventory) | 2 837 | 795 |
| 7 | click '#add-to-cart-sauce-labs-backpack' | 28 | 7 |
| 8 | click '.shopping_cart_link' | 13 | 6 |
| 9 | describe (cart) | 944 | 274 |
| 10 | assert '.inventory_item_name' 'Sauce Labs Backpack' | 55 | 14 |
| | **Toplam A** | **4 669** | **1 308** |

- `assert-text` komutu yok (`Unknown command`). Doğru komut: `assert <selector> [text]`. Sonuç: PASS.
- `describe` ekran görüntüsünü satıra gömmez. Dosya yolu yazar (`/tmp/cdpilot-describe-*.png`, 800×600). Bu görüntü A'ya girmedi.
- Adım 1 `go` çıktısı sayfa metnini de basar (38 token).
- 3 describe = 1 224 token = A'nın %93,6'sı. Adım 6 tek başına %60,8.

## a11y-snapshot, describe, shot karşılaştırması (3 sayfa)

Ekran görüntüsü: 800×600 px → ceil(800/28) × ceil(600/28) = 29 × 22 = **638** görsel token (3 sayfada aynı).

| Sayfa | a11y-snapshot (kar / tok) | describe (kar / tok) | shot (px / tok) | shot ÷ a11y | shot ÷ describe |
|---|---|---|---|---|---|
| login | 182 / 58 | 555 / 155 | 800×600 / 638 | 11,0× | 4,1× |
| inventory | 1 243 / 384 | 2 831 / 795 | 800×600 / 638 | 1,66× | 0,80× |
| cart | 386 / 126 | 944 / 274 | 800×600 / 638 | 5,06× | 2,33× |

- `describe` = a11y-snapshot + sayfa metni (ilk 2000 karakter) + ekran görüntüsü yolu.
- a11y-snapshot en ucuz yapısal çıktıdır. Inventory sayfasında `describe` ekran görüntüsünden pahalıdır (795 > 638).
- Not: bu sayfalar küçüktür. 27.09 ölçümünde HN ve GitHub sayfalarında a11y 8 K token verdi. Büyük sayfada A artar.

## Hesap

| Senaryo | Formül | Token |
|---|---|---|
| A | 10 adım çıktı | 1 308 |
| B | 10 × 5 769 | 57 690 |
| C | 169 (ad) + 637 (navigate 89, describe 95, fill 121, click 209, assert 123) | 806 |
| Senaryo 1 | A + B | 58 998 |
| Senaryo 2 | A + C | 2 114 |

Faz 3 hedefi "10 adım < 30 K":

| Senaryo | Sonuç | Pay |
|---|---|---|
| 1 (hepsini yükleyen istemci) | 58 998 → hedefi AŞAR | −28 998 |
| 2 (Claude Code tarzı) | 2 114 → hedefin altında | +27 886 |

Senaryo 1'i hedefe indirmek için şema yükü 10 istekte ≤ 28 692 token olmalı. Bu istek başına ≤ 2 869 token eder. Şu an 5 769. Gereken kesinti: en az %50,3.

## Yorum

Senaryo 1'de baskın kalem şema yüküdür: 57 690 / 58 998 = %97,8. Çıktı toplamı yalnız %2,2'dir. Senaryo 2'de şema tek sefer ve kısa olduğundan çıktı payı %61,9'a çıkar (1 308 / 2 114). Faz 3 için en büyük kaldıraç şemayı küçültmektir (45 araç, 2 256 token yalnız inputSchema). Ya da istemciye ad-önce, şema-sonra (tembel) yükleme sağlamaktır.

## Sınırlar

- Bu saucedemo görevi küçük sayfalıdır. Büyük sayfada A artar (27.09: HN describe 8 848 token).
- Claude tokenizer'ı yerine o200k proxy kullanıldı.
- MCP `tools/call` zarfı ve MCP'de `describe` görüntüsünün satır içi dönüp dönmediği ölçülmedi.
- Tek koşu. Tekrar varyansı ölçülmedi.
- `git status` anında `src/cdpilot.py` değişikliği vardı. Bu çalışma onu değiştirmedi (başka oturumun işi).

## Ham dosyalar

Dizin: `/Users/nadir/01dev/cdpilot/.claude/docs/token-taban-ham/`

- `mcp-raw.jsonl`, `mcp-stderr.txt`, `mcp-token-tablo.json` (şema)
- `adim01.txt` … `adim10.txt` (10 adım çıktısı)
- `login|inventory|cart-a11y.txt`, `*-describe.txt`, `shots/*.png`
- `hesap.json` (bütün sayılar), `tok.py`, `hesap.py` (betikler)
