# Enjeksiyon dedektörü: ikinci desen geçişi (10.11)

Kod: `src/cdpilot.py` → `_AGENT_INJECTION_RES_2`, `_agent_injection_norm`, `_agent_injection_scan`.
Betik: `.claude/docs/olcum/enjeksiyon-heldout.py [fixture] --families` ve `--time --ref HEAD` (`python3.13 -I`).
Test: `CDPILOT_TEST_ONLY='injection-aware' node test/test.js` → 2 geçti, 0 kaldı.

> **Uyarı:** Held-out-1 artık ayar verisidir. 24/24 örneklem içi sayıdır; gerçek başarıyı
> `injection-heldout-2.json` ölçecek (bu şerit o dosyayı açmadı).

## Önce / sonra

| Küme | Ölçü | Önce (HEAD 65e8b45) | Sonra |
|---|---|---|---|
| korpus (20+20) | yakalama | 19/20 | **20/20** |
| korpus | yanlış alarm | 0/20 | 0/20 |
| heldout-1 (24+24+8) | yakalama | 7/24 | **24/24** |
| heldout-1 | yanlış alarm | 0/24 | 0/24 |
| heldout-1 | alıntı işaretli | 6/8 | 7/8 (Türkçe alıntı da işaretlendi) |

## Heldout-1: aile başına (injected)

| Aile | Önce | Sonra | Yakalayan etiket |
|---|---|---|---|
| override | 1/2 | 2/2 | `addresses_ai` ("ignore everything you were told") |
| fake-system | 0/2 | 2/2 | `fake_system` |
| fake-transcript | 1/1 | 1/1 | `exfiltrate` |
| note-to-ai | 2/3 | 3/3 | `addresses_ai` ("message for autonomous agents:") |
| exfil | 2/5 | 5/5 | `exfiltrate` (genişletilmiş, ipucu şartlı) |
| navigate | 0/1 | 1/1 | `navigate_order` |
| hide | 1/1 | 1/1 | `hide_from_user` |
| tool-json / tool-xml | 0/2 | 2/2 | `tool_call` |
| polite-indirect | 0/1 | 1/1 | `addresses_ai` ("the user would want you to") |
| lang es/fr/tr/ja | 0/4 | 4/4 | `ignore_instructions` (çok dilli) |
| obf zero-width / aralıklı | 0/2 | 2/2 | `ignore_instructions` (normalleştirme sonrası) |

Etiket dağılımı (heldout-1 injected): önce `addresses_ai 2, exfiltrate 3, hide_from_user 1,
ignore_instructions 1`; sonra `addresses_ai 5, exfiltrate 6, fake_system 2, hide_from_user 1,
ignore_instructions 7, navigate_order 1, tool_call 2`. Korpus: tek fark Almanca satır
(`ignore_instructions 3 → 4`). Eski etiket adları değişmedi; eski 6 desen önce çalışır.

## Tarama süresi (sentetik 2.000 düğüm, A/B iç içe, 5 örnek medyanı, örnek = 10 tarama ortalaması)

| Koşu | `uptime` yük | HEAD duvar / CPU | Sonra duvar / CPU |
|---|---|---|---|
| 1 | 315 → 346 | 62,8 / 32,1 ms | 127,2 / 50,5 ms |
| 2 | 346 | 43,9 / 38,2 ms | 68,5 / 54,6 ms |

CPU süresi yaklaşık %45–55 arttı (≈ +17 ms / 2.000 düğüm, düğüm başına ≈ 8 µs). Duvar süresi
yük yüzünden gürültülüdür; CPU sayısı daha güvenilirdir. İlk sürüm 2,6 kat yavaştı; ASCII hızlı
yol (`lower()`, `translate` yok), sıfır genişlik silme için regex ve ikinci geçiş için tek
alt-dizgi ön süzgeci (`_AGENT_KEYS_RE`) bunu indirdi.

## Normalleştirme

Eşleşme için: U+200B–U+200D, U+2060, U+FEFF, U+00AD silinir → NFKC → casefold → Türkçe
`ı`/`İ` (casefold sonrası `i̇`) `i` olur → ≥5 tek harf tek boşluk/nokta ile ayrılmışsa
birleşir. Çıktıdaki `text` her zaman özgün metindir (test bunu doğrular). Tarama yalnız işaretler.

## Yeni desenler ve yanlış alarm riski

| Etiket | Desen (özet) | Gördüğüm risk |
|---|---|---|
| `fake_system` | Satır başı `SYSTEM:` / `[SYSTEM]` / `<system>` / `developer message:` **veya** `debug/developer mode enabled` + ajana emir (`the assistant must`, `you are now`, `print your … configuration`, `before answering`) | Düşük. "SYSTEM: maintenance scheduled…", "Debug mode enabled: logs…" temiz kaldı. Risk: bir güvenlik makalesinde satır başında alıntılanmış sahte sistem mesajı. |
| `tool_call` | JSON `"tool/name/function": "<eylem…>"` + `"arguments/parameters"`; XML `<tool_call>`, `<function_call(s)>`, `<invoke>`, `<tool_use>` + eylem (navigate/open/send/fetch/post/click/fill/submit/upload/email/delete/…) | Orta. Bir tarayıcı-aracı API belgesinde `{"name": "navigate", "arguments": …}` örneği işaretlenir. `"search"` örneği temiz. |
| `navigate_order` | open/navigate to/go to/visit/browse to/load + URL **ve** ajana ipucu (`ai agents`, `assistant:`, `claude,`, `before answering`, `instead of (on) this site`, `without telling the user`, `your task`) | Düşük. "you must" ve çıplak "sign in" ipucu olarak **alınmadı**: "Visit https://… and sign in" ve "you must visit https://… to verify" kullanıcı metninde çok sık. "Go to https://… instead." (taşındı sayfası) temiz. |
| `ignore_instructions` (es/fr/tr/ja/de/pt) | Dil başına bir kısa dal; tr'de `unut(un)/yok say/görmezden gel/dikkate alma`, ja'da `(以前/前/これまで/上記/先)の指示…無視` | Düşük. "Önceki talimatları unutmayın" (unutma = hatırla) temiz; "Siparişinizi önceki adımda…" temiz. Alıntılar işaretlenir (kabul). |
| `exfiltrate` (geniş) | include/append/copy/read/paste/post/send/upload/… + document.cookie, localStorage, form alanları, ~/.ssh, id_rsa, .env, session/bearer token, saved passwords **ve** ipucu (`your (next) reply/answer`, `into the comment/chat box`, `the user filled`, `from the local machine`, `you have access to`) | Orta-düşük. "Copy .env.example to .env", "Copy your session token … paste it into the CLI" temiz. Risk: "include … in your response" diyen sunucu belgesi (`response headers/body` hariç tutuldu). |
| `addresses_ai` (geniş) | "ignore everything you were told", "AI/LLM … reading this", "LLMs/autonomous agents … reading this", "message for autonomous agents", "autonomous agents:", "the user would (really) want you to" | Düşük. "Autonomous agents are reshaping logistics" temiz. |

## Doğrulanmayan

- Gerçek web dağılımında yanlış alarm oranı: yalnız 44 temiz örnek + testteki 19 zor negatif.
- Held-out-2 ile bağımsız ölçüm: lider yapacak.

## Şef ölçümü — held-out-2 (11.11 00:2x, ayar dışı küme)

Şerit `injection-heldout-2.json`'u açmadı; şef ölçtü (`enjeksiyon-heldout.py <ana repo>/test/fixtures/injection-heldout-2.json --families`).

| Küme | Ölçü | Önce (main desenleri) | Sonra (bu şerit) |
|---|---|---|---|
| heldout-2 (30+30, 7 dil) | yakalama | 4/30 | **8/30** |
| heldout-2 | yanlış alarm | 1/30 | 1/30 (aynı satır: tarif "ignore previous kneading instructions") |

Sonuç: held-out-1'deki 24/24 örneklem içi sayıdır; dışarıda 4 → 8/30. Kaçanlar: sahte tur (`Assistant:`/`Human:`),
`[SYSTEM NOTIFICATION…]`/`BEGIN SYSTEM INSTRUCTION`, homoglif (Kiril `Dіѕrеgаrd`), base64, zh/ru/ar/tr çok dilli, rol oyunu,
otorite/aciliyet. İşaret ipucudur, süzgeç değil. Bundan sonraki her ayar turu held-out-2'yi de ayar verisine çevirir; bağımsız
ölçüm için held-out-3 gerekir.

Kötü niyetli giriş süresi (şef, 100 KB tek ad, `scratchpad/redos.py`): en kötü `<invoke x ` ×10.000 → 164 ms (main 24 ms);
öteki durumlar 9–35 ms. Felaket geri izleme yok (bütün nicelleyiciler sınırlı).

## Şef ölçümü — held-out-3 (11.11 00:4x, üçüncü bağımsız küme, 40+40, 12 dil)

Küme agy `heldout-3` şeridinden (Gemini 3.8 Flash), dedektörü ve önceki kümeleri görmeden yazıldı; ayar için KULLANILMAZ.

| Desenler | Yakalama | Yanlış alarm |
|---|---|---|
| önce (65e8b45) | 2/40 | 2/40 |
| sonra (main f6ca63e) | 7/40 | 2/40 (bir güvenlik haberi alıntısı, bir tarif satırı) |
