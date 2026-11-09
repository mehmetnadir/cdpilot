# Öğrenen akış — `agent flow` / `agent run` (PRD v0, karar 09.11.2026)

Durum: UYGULANDI v0 (Nadir 09.11: "kararları kendin alabilirsin, devam et"; şef kararı D-0035, iş K-0017).
Problem: bir LLM aynı tarayıcı işini her oturumda yeniden öğrenir. Aynı giriş, aynı menü, aynı form; her adımda
sayfa okunur, token harcanır, saniyeler geçer. Çözüm: ilk koşuda LLM adımları atar, cdpilot adımları çapasıyla
kaydeder; ikinci koşuda aynı iş LLM'siz, daemon hızında yeniden oynar. LLM yalnız sayfa değiştiğinde ve yalnız
değişen adım için çağrılır.

```
ilk koşu:   agent observe → agent act --ref … (×N)  ──▶ iz (agent-state.trail, maskeli)
                                                            │ agent flow save <ad>
                                                            ▼
                                                   flows/<ad>.json (çapa = rol + ad + sıra)
ikinci koşu: agent run <ad> ──▶ adım: AX ağacı → çapa bul → eylem → son koşul (host)
                 │ sapma yok: LLM'e 0 token, sonuç tek JSON
                 └ sapma: çıkış 4 + o sayfanın gözlemi → LLM yalnız o adımı yeniden planlar → act → flow save
```

## 1. Kapsam v0 (yalnız bunlar)

| Komut | İş |
|---|---|
| (otomatik) | her `agent act` ize girer: eylem, çapa `{role, name, nth}`, metin (maskeli), önce/sonra URL. Son 50 adım. Kullanıcı eforu sıfır. |
| `agent flow save <ad> [--last N]` | izden akış dosyası yazar (varsayılan: son `go`dan bu yana). Sırlar `{{vN}}`; değer diskte yok. |
| `agent flow list` / `show <ad>` / `delete <ad>` | akışlar; `list` host, adım, koşu/sapma sayısı verir |
| `agent run <ad> [--var k=v] [--dry-run]` | çapayla yeniden oynatır; her adımda "LLM okusaydı kaç token" toplar (`tokens_avoided`) |
| `agent observe` | sayfanın host'una kayıtlı akış varsa `known_flows: [ad…]` ekler (yoksa alan yok) |

Dışarıda (v1+): akışların paylaşımı, seçici yedeği (CSS), otomatik `save` önerisi,
koşullu adımlar, bekleme adımı.

## 2. Çapa ve sapma kuralı

Çapa = AX rolü + erişilebilir ad + aynı rol/ad içindeki sıra (`nth`). DOM kimliği ve `@ref` kaydedilmez; onlar oturuma
bağlıdır. Eşleme sırası: tam eşleşme → büyük/küçük harf duyarsız → ad içerir (rol aynı). Birden çok aday → `nth`.
Aday yok → SAPMA. Eylem sonrası kayıtlı host ile şimdiki host farklı → SAPMA.

Sapmada `agent run`:
- çıkış kodu 4 (0 başarı, 2 eksik değişken/dosya, 1 başka hata)
- stdout tek JSON: `{status:"drift", flow, step, expected:{role,name,nth}, url, title, actions:[…], text}` — yani o
  sayfanın tam gözlemi; LLM ikinci bir `observe` yapmaz.
- `@ref`ler geçerli kalır; LLM `agent act --ref` ile adımı atar, sonra `agent flow save <ad>` akışı düzeltir.
- Onarım zincirleme yayılmaz: yalnız sapan adım değişir; kalan adımlar yeni koşuda yeniden denenir.

## 3. Güvenlik

- Maskeleme kayıt anında, agent-state'e yazılmadan önce: alan adı sır gibi (`pass|pwd|token|secret|key|otp|…`) ya da
  metin jeton biçimli (`_slog_tokenish`, jeton ön eki) → `{{vN}}`; URL'ler oturum günlüğü kuralıyla maskelenir.
- `agent run` değişkeni `--var k=v` ya da `CDPILOT_VAR_<K>` ile alır; eksikse hiçbir adım koşmadan çıkış 2.
- `--dry-run` değer basmaz. Akış dosyası 0600 değil (sır yok), ama `~/.cdpilot/projects/<id>/flows/` altında.
- Yanlış eylem sessiz geçmez: son koşul (host) tutmazsa sapma; sonuç JSON her adımı listeler.

## 4. Ölçüm ve kapılar

| Kapı | Hedef | Nasıl |
|---|---|---|
| Tekrar eden işte LLM token'ı | ≥ %90 azalma (3+ adımlı iş) | `agent run` sonucu `tokens_avoided` (adım başına tam gözlem tahmini toplamı) ÷ sonuç JSON tahmini; gerçek sayfa ölçümü bu belgede §6 |
| Süre | bilinen 3 adımlı iş ≤ 1 sn sıcak | olc.sh yöntemiyle, ortak başsız Chrome 9333 |
| Sapma davranışı | yanlış öğeye tıklama 0; aday yok → çıkış 4 | sahte CDP testi (ağaç değişince) |
| Sır | akış dosyasında ve agent-state'te sır metni 0 | test: "Password" alanına yazılan değer diskte aranır |
| Gerileme | mevcut agent testleri, daemon paritesi | `node test/test.js`, tutanak `TT-…` |

## 5. Var olan çözüm sorusu (hesaplamadan-önce §0)

| İhtiyaç | Var mı | Karar |
|---|---|---|
| Adım kaydı | `record start/stop` (CLI komutlarını ham argümanla kaydeder; `@ref` oturuma bağlı → yeniden oynamaz) | kullanılmaz; iz AX çapasıyla ayrı tutulur, maskeleme yardımcıları (`_slog_tokenish`, `_SLOG_SECRET_NAME_RE`, `_slog_mask_url`) ortak |
| Yeniden oynatma | `replay` (çocuk süreç başına komut) | kullanılmaz; `agent run` aynı süreçte, daemon sıcak |
| Sayfa gözlemi | `_agent_full_snapshot`, `_diff_snapshots` | kullanılır |
| Eylem | `cmd_agent_act` gövdesi | `_agent_perform` olarak ayrılır, iki yer kullanır |
| Değişken sözdizimi | `replay --var k=v`, `CDPILOT_VAR_<K>` | aynı sözleşme |

## 6. Ölçüm sonuçları (09.11, M1 Max, yük 40, ortak başsız Chrome 9333, sıcak süreç)

Düzenek: 3 sayfalık yerel fixture (`a.html` 6,4 KB: 15 bağlantılı menü, form, 12 paragraf → `b.html` 8 öğe + Confirm →
`c.html`). İş: aç, Search doldur, Next'e tıkla, Confirm'e tıkla. Betik `scratchpad/akis/olc-akis.sh`, çıktı `olc-akis.out`.

| Ölçü | Model döngüde (go + observe + 3 act) | `agent run` (3 koşu) | Fark |
|---|---|---|---|
| Model okur | 5.049 token (observe 1.779 + act diff'leri) | 237 token (tek sonuç JSON) | −%95,3 |
| Tam gözlem eşdeğeri (`tokens_avoided`) | — | 6.412–6.418 | üst sınır: adım başına tam observe |
| Duvar süresi | 1.655 ms (5 komut) | 638–706 ms (iç 527–577) | −%60; LLM bekleme süresi ayrıca sıfır |
| Sapma denemesi (Next → "Continue to review") | — | çıkış 4, adım 3, `anchor not found`, aday listesi sayfadan | tahmin yok |

Not: `tokens_avoided` adım başına tam gözlemi sayar; diff kullanan bir ajan daha az okur (ölçülen 5.049). Yük 40
altında mutlak süreler 2–3× şişkin; oran geçerlidir. Model gecikmesi (adım başına saniyeler) tabana dahil değildir;
gerçek kazanç ondan büyüktür.

## 7. İkinci hat (ayrı commit, 09.11): enjeksiyon farkındalı gözlem — UYGULANDI v0

`_agent_injection_scan(nodes)`: AX düğüm adlarında ajana hitap eden metni 6 dar desenle tarar
(`ignore_instructions`, `addresses_ai`, `system_prompt` yalnız emirle, `new_instructions`, `hide_from_user`, `exfiltrate`);
`agent observe` (tam ve diff), `agent act` diff'i (metin değiştiyse) ve `agent run` sapma sonucu `injection_suspect: [{text, match}]`
taşır (en çok 5, yoksa alan yok). Metin gizlenmez, engellenmez; model işareti metnin yanında görür. AX `ignored` düğümler
taranmaz (zaten metinde yok). Birim testi: 11 işaretli / 10 temiz cümle (yapay zekâ *hakkında* sayfa işaretlenmez); sahte
example.com ağacında bir enjeksiyon satırı, uçtan uca test.

Sınır (bilinçli): görünmez-ama-AX'te metin (beyaz üstüne beyaz, ekran dışı) ayırt edilmez; desen İngilizce; `go`/`content`
çıktısına girmedi. Ölçüm için sıradaki iş: 20 gerçek enjeksiyon örneği + 20 temiz sayfa ile yakalama/yanlış alarm oranı.

## 8. MCP araçları (09.11, aynı gün)

`browser_agent_observe` (`diff`), `browser_agent_act` (`ref`/`url`, `action`, `text`), `browser_agent_flow_save` (`name`, `last`),
`browser_agent_run` (`flow`, `vars` nesnesi, `dry_run`). `core` profili dışında (`browser_tools enable`). Sapma / eksik değişken
`isError` + komutun JSON'u. Sınır: MCP sunucusu her çağrıda taze Python süreci açar; daemon sıcak yolu MCP'de yok → HIZ adayı.
