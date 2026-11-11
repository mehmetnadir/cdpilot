# `agent observe` token diyeti (o200k, 11.11)

> Sayım: tiktoken `o200k_base`, kompakt UTF-8 JSON (bugünkü basılan biçim). Veri: `~/01dev/cdpilot-olcum-ham/json-bicim-2026-11-11/observe-*.json`.
> Betik: `.claude/docs/olcum/observe-diyet.py` (sayfa yeniden çekilmedi). Kod değişmedi; bu belge ölçüm ve tasarımdır.
> Yük: ölçüm betiği saf Python, CPU hafif. Tüm sayılar kayıtlı çıktıdan gelir.

## 1. Özet

| Bulgu | Sayı |
|---|---|
| Girdi başına maliyet | ref %18–22, role %15–19, ad %39–50, yapı (`{},:"`) %18–22 |
| Eylemlenemez rol payı (landmark dahil) | %41–61 token |
| `text` alanı | 3–89 token. Boş sayılır (kod hatası, bkz. §3) |
| En büyük kaldıraç | 1) eylemlenemez rolleri çıktıdan düşmek 2) satır/dizi biçimi |
| Kısa anahtar (`r`,`k`,`n`) | 0 kazanç: `ref`, `role`, `name` zaten tek token |
| Ad kırpma (80 kar.) | %0–6 |
| Kap girdisini düşürme | %0–17 (yalnız MDN) |

## 2. Anatomi

### 2.1 Alana göre (o200k, toplam çıktının payı)

| Sayfa | Toplam tok | Girdi | ref | role | name | yapı | url+title | text | token_estimate |
|---|---|---|---|---|---|---|---|---|---|
| hn | 6.115 | 349 | 1.396 (%22) | 1.088 (%17) | 2.548 (%41) | 1.396 (%22) | 16 | 3 | 6 |
| enwiki | 17.081 | 963 | 3.852 (%22) | 3.328 (%19) | 6.692 (%39) | 3.852 (%22) | 16 | 22 | 6 |
| mdn | 5.810 | 330 | 1.320 (%22) | 1.113 (%19) | 2.303 (%39) | 1.320 (%22) | 25 | 21 | 6 |
| trwiki | 9.729 | 524 | 2.096 (%21) | 1.665 (%17) | 4.292 (%44) | 2.096 (%21) | 36 | 24 | 6 |
| jawiki | 17.001 | 791 | 3.164 (%18) | 2.674 (%15) | 8.598 (%50) | 3.164 (%18) | 60 | 89 | 6 |

Not: alan token sayıları parça parça sayılır; sapma küçüktür. `href`, `value` ve başka alan yok: üç alan var (`ref`, `role`, `name`). Linkin hedefi çıktıda görünmez.
Yapı payı sabittir: her girdi `{"ref":"@N","role":"…","name":"…"}` kalıbını taşır. Bu kalıp girdi başına ~4 token yapı + ~4 token ref ekler.

### 2.2 Role göre (girdi sayısı / token payı)

| Sayfa | link | StaticText | cell/LayoutTableCell | ListMarker | button | landmark (heading, region, navigation) | Diğer (Abbr, term, row/columnheader, image) |
|---|---|---|---|---|---|---|---|
| hn | 229 / %64,5 | 33 / %9,1 | 86 / %36,9 | 0 | 0 | 0 | 0 |
| enwiki | 488 / %48,5 | 371 / %50,2 | 4 / %0,5 | 48 / %4,8 | 8 / %0,8 | 21 / %2,1 | ~22 |
| mdn | 77 / %23,1 | 93 / %31,0 | 35 / %13,5 | 0 | 69 / %25,3 | 10 / %3,3 | ~45 |
| trwiki | 391 / %68,1 | 69 / %18,2 | 20 / %14,0 | 1 | 4 / %0,8 | 14 / %2,8 | ~24 |
| jawiki | 461 / %47,2 | 261 / %50,4 | 13 / %4,0 | 21 / %2,1 | 4 / %0,3 | 16 / %1,9 | ~15 |

(Pay sütunları kendi girdi tokeninin toplam çıktıya oranıdır. Tam rol tabloları betik çıktısında.)

### 2.3 Eylemlenemez girdi, kopya ad, uzun ad

Eylemlenebilir = `AGENT_INTERACTIVE_ROLES` + `DisclosureTriangle` (MDN'de görüldü, listede yok). Eylemlenemez = geri kalan (landmark dahil).

| Sayfa | Girdi | Eylemlenebilir | Eylemlenemez | Eylemlenemez tok | Pay | Kopya (rol+ad) fazla girdi / tok | Ad > 80 kar. (adet / tok payı) |
|---|---|---|---|---|---|---|---|
| hn | 349 | 230 | 119 | 2.817 | %46,1 | 79 / 1.225 | 4 / %1,5 |
| enwiki | 963 | 497 | 466 | 10.261 | %60,1 | 163 / 2.493 | 37 / %6,2 |
| mdn | 330 | 147 | 183 | 3.546 | %61,0 | 33 / 671 | 3 / %1,0 |
| trwiki | 524 | 395 | 129 | 3.969 | %40,8 | 63 / 1.028 | 24 / %13,8 |
| jawiki | 791 | 465 | 326 | 10.286 | %60,5 | 120 / 1.936 | 21 / %9,5 |

Kopya adlar: HN'de 31 boş adlı link, enwiki'de 42 `^` linki, jawiki'de 33 `英語版` linki. Bu kopyaların nth sırası ankrajda anlam taşır (`nth`); düşürmek ankrajı kaydırır, bu yüzden kopya düşürme seçeneği tablodan çıkarıldı (§4, G).
HN'de `cell` girdileri hikâye başlığını ve "531 points by … | hide | 108 comments" satırını taşır. Bu satır puan ve yorum sayısının tek kaynağıdır.

## 3. Neden eylemlenemez roller `actions` içinde? (kod)

`src/cdpilot.py` (098 worktree):

| Satır | Kod | Anlamı |
|---|---|---|
| 15963–15967 | `AGENT_INTERACTIVE_ROLES = {'button','link','textbox',…,'gridcell'}` | Rol listesi. `cell`, `StaticText`, `heading`, `DisclosureTriangle` listede yok |
| 15974–15977 | `AGENT_SKIP_ROLES = {'none','presentation','generic','LineBreak','InlineTextBox',…}` | Atılan roller. `StaticText`, `cell`, `LayoutTableCell`, `ListMarker` buraya girmez |
| 16495 | `is_interactive = role in AGENT_INTERACTIVE_ROLES` | Liste testi |
| 16496–16501 | `# text-anchor fallback: unique non-empty name with any role` / `is_text_anchor = (not is_interactive and len(name) > 2 and seen_names.get(name, 0) == 0)` | **Kök neden.** İlk görülen, 3+ karakterli her adlı düğüm "metin çapası" olarak girer: rol ne olursa olsun |
| 16502–16503 | `if not is_interactive and not is_text_anchor: continue` | Yalnız eylemlenebilir olmayan ve çapa olmayan düğüm elenir |
| 16505 | `seen_names[name] = seen_names.get(name, 0) + 1` | Yalnız ilk görülen ad çapa olur; sonraki aynı adlı eylemlenemez düğüm elenir |
| 16461 | `text_roles = {'staticText', 'text', 'paragraph', 'heading'}` | **Hata:** AX rolü `StaticText` (büyük S). `staticText` hiç eşleşmez. `text` alanı bu yüzden yalnız `heading` ve `paragraph` metnini toplar: 3–89 token |

Sonuç: `actions` listesi iki işi birden yapıyor. (1) eylemlenebilir düğüm adresi. (2) sayfa metninin vekili. `text` alanı kırık olduğu için model sayfa metnini bugün yalnız eylemlenemez girdilerden okuyor. Eylemlenemez girdileri düşürürsek `text` düzeltmesi gerekir (§4, A+metin).

Ankraj ve `act` yolu:

| Satır | Davranış | Seçenek için anlamı |
|---|---|---|
| 16558–16560 | `actions = _snapshot_to_actions(nodes, state)`, sonra `state['actions_map'] = {a['ref']: a …}` | Durum tam listeyi tutar |
| 16581–16584 | `out_actions` = yalnız `backend_node_id` düşürülmüş kopya | Çıktı listesi ayrı bir kopyadır: süzgeç buraya konabilir |
| 17489 | `_agent_find_anchor(anchor, actions)` (`agent run`) | Ankraj tam listede aranır, çıktıyı değil |
| 17240–17243 | `nth = same.index(desc['ref'])`, `same` = aynı rol+ad girdileri | nth rol+ad grubuna bağlı. Bir rolün tüm grubu düşerse başka grubun nth'i kaymaz |
| 16742–16744, 16763 | `act --ref` → `old_map[ref]` | Ref tam haritada çözülür |
| 16836–16839 | sapma çıkışı 4 | Sapma yanıtı `out_actions` + `text` basar (17453, 17473 civarı) |

## 4. Seçenekler (prototip: `observe-diyet.py`; yüzdeler tabana göre azalma)

Ortak tasarım ilkesi: süzgeç yalnız **çıktıya** uygulanır. `actions_map`, ref sayacı ve `agent run` ankraj araması tam listede kalır. Böylece kayıtlı akış ve `act --ref` etkilenmez.

### 4.1 Toplam çıktı tokeni

| Sayfa | Taban | A süzgeç | A + landmark | A + landmark + metin düzeltmesi | B ad kırpma (80) | C kopya/kap | E1 kısa anahtar | E2 dizi satırı (A üstünde) | E3 metin satırı (A üstünde) | D bütçe 3000 | D bütçe 1500 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hn | 6.115 | 3.532 (−%42) | 3.532 (−%42) | 3.627 (−%41) | 6.107 (−%0) | 6.087 (−%0) | 3.532 (−%42) | 2.118 (−%65) | 1.706 (−%72) | 2.661 (−%56) | 1.326 (−%78) |
| enwiki | 17.081 | 7.520 (−%56) | 7.816 (−%54) | 7.911 (−%54) | 16.736 (−%2) | 16.993 (−%1) | 7.520 (−%56) | 4.529 (−%73) | 3.462 (−%80) | 2.623 (−%85) | 1.315 (−%92) |
| mdn | 5.810 | 2.607 (−%55) | 2.746 (−%53) | 2.947 (−%49) | 5.800 (−%0) | 4.838 (−%17) | 2.607 (−%55) | 1.724 (−%70) | 1.429 (−%75) | 2.616 (−%55) | 1.324 (−%77) |
| trwiki | 9.729 | 5.991 (−%38) | 6.257 (−%36) | 6.514 (−%33) | 9.130 (−%6) | 9.681 (−%0) | 5.991 (−%38) | 3.619 (−%63) | 2.753 (−%72) | 2.656 (−%73) | 1.335 (−%86) |
| jawiki | 17.001 | 7.344 (−%57) | 7.629 (−%55) | 8.615 (−%49) | 16.444 (−%3) | 16.864 (−%1) | 7.344 (−%57) | 4.548 (−%73) | 3.708 (−%78) | 2.670 (−%84) | 1.346 (−%92) |

Notlar:
- "A + landmark + metin düzeltmesi": `text` alanı düşen StaticText adlarını 2000 karaktere kadar toplar. Sütun "A+metin" prototipte landmark'sız A üstünde; landmark'lı sürüm §4.3'te.
- E1: `ref`, `role`, `name` anahtarları o200k'de zaten tek token. `r`,`k`,`n` kazandırmaz. **Önerilmez.**
- C kopya/kap (sıra tabanlı sezgi + ad eşitliği): yalnız MDN'de anlamlı (50 landmark/başlık adı eylemlenebilir bir linkle aynı). Concat kapı HN'de 0: hücre adı ("Başlık (alan.adı)") ardışık girdilerin birleşimi değil, link adları hücrelerden ayrı sırada gelir. Gerçek uygulama AX `childIds` ile çalışırsa farklı çıkabilir; ölçülen alt sınır %0–17.
- B ad kırpma: 80 karakterde (79 + `…`) %0–6. (rol, ad) çifti birleşmedi (tüm sayfalarda 0 birleşen çift), yani kırpma yeni kopya yaratmadı. `name` ucundaki ek bilgi kaybolur (HN başlığında alan adı).
- D bütçe: AX sırasıyla ilk N girdi, `more:{n,from}` imleciyle. 1.500 bütçe ~80 girdi sığdırır, 3.000 bütçe ~160. **Görüş alanı sırası prototiplenemedi:** kayıtlı veride kutu konumu yok. Bütçe AX sırasında keser; footer ve menü girdileri önde, hedef link sonda olabilir. Görüş-önce sıra için `DOM.getBoxModel`/`DOMSnapshot` gerekir (girdi başına ek CDP çağrısı, hesaplanmadı).

### 4.2 Her seçenek: kayıp, akış etkisi, `act`/`--diff` etkisi, risk

| Seçenek | Model neyi kaybeder | Kayıtlı akış (`agent run`) | `act` ref ve `--diff` | Risk |
|---|---|---|---|---|
| A. Eylemlenebilir rol süzgeci (yalnız çıktı) | Sayfa metni (StaticText), tablo hücresi içeriği. HN'de puan/yorum/yaş satırı (`cell`) kaybolur | Etkisiz: `agent run` tam listede arar (17489). Çıktı yerine kaynakta uygulanırsa StaticText/cell ankrajlı akış kayıp (sapma, çıkış 4). nth kaymaz (grup düşer) | Gizli ref'e `act --ref` hâlâ çalışır (harita tam). `--diff` `added` listesine aynı süzgeç uygulanmalı; `removed` gizli ref'i listelememeli | Orta: sayfa metni yok sayılırsa model içeriği okuyamaz. `text` düzeltmesi şart |
| A+landmark | Landmark dışı roller | A ile aynı | A ile aynı | Düşük. +%2–3 token, yön bulmaya yarar |
| A+metin düzeltmesi (`text_roles` `StaticText`) | Hiçbir şey; kaybı geri alır | Etkisiz | `text_changed` karması değişir: tüm `--diff` ilk çağrıda tam metin basar (bir kez) | Düşük. `text` 2000 karakter sınırını korur |
| B. Ad kırpma | Uzun adın kuyruğu (>80 kar.) | Etkisiz: ankraj tam adı tutar (state tam adı saklar). Çıktıya kırpık ad girer; model `agent act --ref` kullanır, ad yazmaz | Etkisiz | Düşük. Kırpma sonrası (rol, ad) birleşmesi ölçüldü: 0. Model uzun adı düz metinde arayacaksa bulamaz |
| C. Kopya/kap girdisini düşürme | Kap adı; çocukların birleşimi zaten listede | Etkisiz (çıktı süzgeci) | Etkisiz | Düşük risk, düşük kazanç (%0–17). HN'de kayıp var: kap adındaki "531 points" çocuklarda yok, düşürülürse puan gider. Ad eşitliği kuralı bunu düşürmez |
| D. Bütçe + `more` imleci | Bütçe dışı girdiler. AX sırası hedefi gizleyebilir | Etkisiz | Gizli ref geçerli. `more` için yeni argüman (`observe --from N`) | Yüksek: model `more` çağırmazsa eylemi bulamaz. Görüş-önce sıra olmadan zararlı |
| E1. Kısa anahtar | Okunabilirlik | Etkisiz | Çıktı şeması değişir (MCP araç açıklaması, testler) | Kazanç sıfır (o200k). Yapma |
| E2. Satır dizisi `["@3","link","Guidelines"]` | Alan adı yok; sıra sabit olmalı | Etkisiz | `--diff` `added` aynı biçime geçer. Şema değişir: MCP `browser_agent_observe` açıklaması, testler, README, `examples/` | Orta: şema kırılması. Modeller diziyi iyi okur. Kayıt dosyaları (`flows/*.json`) çıktıyı kullanmaz |
| E3. Metin satırı `"@3 link Guidelines"` | Yapı yok; ad içinde satır sonu varsa ayrıştırma | Etkisiz | E2 ile aynı | Orta. En ucuz biçim (−%72…80), ama ad boşlukları nedeniyle rol tek sözcük olduğu sürece ayrışır. E2'den ~%20 küçük |
| G. Kopya adı tek girdiye indirme (`×N`) | Aynı adlı girdilerin ayrı ref'leri | **Bozar:** `nth` kayar | Gizlenen ref'ler | Reddedildi |

### 4.3 Önerilen birleşim

**R = A + landmark (yalnız çıktı) + C (ad kopyası) + B (80) + E2 (dizi satırı) + `text_roles` düzeltmesi.**

| Sayfa | Taban | R (ölçülen) | Azalma |
|---|---|---|---|
| hn | 6.115 | 2.213 | −%64 |
| enwiki | 17.081 | 5.065 | −%70 |
| mdn | 5.810 | 2.090 | −%64 |
| trwiki | 9.729 | 4.303 | −%56 |
| jawiki | 17.001 | 5.974 | −%65 |

(R = `opt_B(opt_C(opt_A(landmark)))` + `tuples` + `text_from_dropped`, betiğin son sütunlarında hesaplanır.)
E3 yerine E2 seçildi çünkü ayrıştırma belirsizliği yok; E3 ek −%7–9 verir (jawiki 4.703 yerine 3.848, metin düzeltmesi hariç). E3 ikinci aşamada denenebilir.
Landmark'ı dışarıda bırakan salt A, enwiki'de ~300 token daha ucuzdur; yön bilgisi için landmark tutuldu.

Kalan risk: HN gibi tablo düzenli sayfada `cell` içeriği (puan, yorum, saat) çıktıdan çıkar. Bu bilgi kritikse `agent observe --full` (bugünkü biçim) açık kalmalıdır.

## 5. Göç yolu (kayıtlı akış bozulmaz)

| Adım | İş | Neden güvenli |
|---|---|---|
| 1 | `_extract_text_summary` içinde `'staticText'` → `'StaticText'` (16461). Tek başına yayınla, ölç | Çıktıyı büyütür (~+100–1000 tok); kimseyi bozmaz. A için önkoşul |
| 2 | `cmd_agent_observe`, `cmd_agent_act`, `agent run` sapması: `out_actions` üretilirken görünürlük süzgeci. `actions_map`, `ref_counter`, `_agent_find_anchor(…, actions)` dokunulmaz | Ankraj ve `act --ref` tam listeyi kullanır; kayıtlı akış aynı sonucu verir. Test: 098 sahte AX ağacı + `agent run` kayıt akışı, çıkış 0 |
| 3 | `--diff`: `added`/`value_changed`/`removed` aynı süzgeçten geçer | Gizli ref'in `value_changed` gürültüsü azalır; `changed` boş kalırsa kısa |
| 4 | B (80) + C: çıktı dönüşümü, durumdan bağımsız | Geri alınır |
| 5 | E2 satır biçimi, `CDPILOT_OBSERVE_FORMAT=objects` ile eski biçim, bir sürüm boyunca varsayılan açık geri dönüş; MCP açıklaması ve README güncellenir | Şema kırılması bu adımda; kayıtlı akışlar çıktıyı okumaz, etkilenmez |
| 6 | `agent observe --full` ve `browser_agent_observe {full:true}` | HN gibi sayfa için bugünkü ayrıntı |
| 7 | İzleme: `tokens_avoided` ve `saved_vs_full` artık süzgeçli çıktıya göre hesaplanır (17481, 16585, 16785). Ayrı alan `tokens_avoided_full` ile eski ölçek korunur | Tarihsel kıyas bozulmaz |

Süzgeç **kaynakta** (`_snapshot_to_actions`) uygulanırsa: StaticText/cell/heading ankrajlı akışlar sapar (çıkış 4). Kaynak bozulmadığı için bu yola **gitmeyin**. Akış etkisi, ölçülen: hiçbir rol grubunun nth'i değişmez (tüm sayfalarda 0). Çıktıdan gizlenecek girdi (A, landmark hariç): hn 119, enwiki 445, mdn 173, trwiki 115, jawiki 310.

Yeniden kayıt: kaynakta uygulanıp bir akış saptıysa kullanıcı `agent observe` → `agent act …` → `agent flow save <ad>` ile yeniden kaydeder (sapma yanıtı hint olarak bunu söyler). Çıktı-yalnız yolda yeniden kayıt gerekmez.

## 6. Dürüst sınırlar

- Görüş-önce sıra ve `DOMSnapshot` maliyeti ölçülmedi (kayıtlı veride konum yok).
- C'nin gerçek sürümü (AX `childIds`) ölçülmedi; sıra tabanlı sezgi alt sınır.
- Modelin eylem seçme doğruluğu ölçülmedi; yalnız token. A+E2 için karar başarısı (aynı görev, eski ve yeni biçim, N tekrar) ayrı ölçüm gerektirir, yayın kapısı olmalı.
- Beş sayfa. Form ağırlıklı sayfa (checkout) ve SPA ölçülmedi.
