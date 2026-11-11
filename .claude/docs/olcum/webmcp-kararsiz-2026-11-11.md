# webmcp e2e kararsızlığı — 11.11.2026

## Sonuç
Ürün hatası. Test sırası ya da pencere sorunu değil.

## Neden
- `tools list`, `WEBMCP_LIST_JS` ile her belgenin `getTools()` çağrısını sırayla bekler (`src/cdpilot.py`).
- Bir belgenin `getTools()` sözü hiç çözülmezse bütün `Runtime.evaluate` asılı kalır.
- 15 sn sonra `_webmcp_eval` "no reply from the page" döner (satır ~19018).
- İzole dünya cevap vermeyince `_webmcp_list` aynı işi ana dünyada bir kez daha dener: 2 × 15 sn.
- Chromium bazı `registerTool()` çağrılarını hiç yanıtlamaz (settle() içindeki not, 153 sürümü). Aynı sınıf hata `getTools()` için de olabilir.

## Kanıt
- İlk deneme (iş 130190020993): önceki 4 webmcp e2e testi geçti. `a --timeout aborts…` testi 04:11'de düştü (önceki testten ~33 sn sonra).
- 33 sn = `until` penceresi (30 sn) + 1 list. Bir list çağrısı 15–30 sn sürdü. Yani tek çağrı asıldı, pencere kısa değil.
- Çıktı: `reason: "error"`, `no reply from the page`. Bu metin yalnız evaluate zaman aşımında çıkar.
- Aynı commit ikinci denemede geçti (iş 130197685603): kararsız, her seferinde değil.
- Önceki testten kalan durum yok: test `go` ile yeni belge yükler, `settle` tüm kayıtların `ok` olduğunu doğrular.
- Doğrulanmadı: asılı olan belgenin üst belge mi iframe mi olduğu. CI günlüğü bunu göstermez.

## Düzeltme
- `getTools()` çağrısı belge başına 5 sn ile sınırlandı (`WEBMCP_GETTOOLS_MS`, `bounded()` hem list hem call betiğinde).
- Asılı iframe: o belge atlanır, kalan araçlar listelenir (`facts.stuck`). Sonraki yoklama tam listeyi alır.
- Asılı üst belge: adı olan hata `TimeoutError: getTools() did not answer within 5000 ms`, `reason: error`, çıkış 0. `until` yeniden dener.
- Süre: 15–30 sn yerine en çok 5 sn. `until` penceresinde 6 deneme sığar.
- Mevcut hiçbir assertion değişmedi. Pencere uzatılmadı.

## Test
- `webmcp: a getTools() that never settles is cut off: the list skips that frame, a stuck top document is a named error`
- Sahte sayfa: `framehang` ve `tophang` senaryoları (`test/webmcp_fake_page.js`), harness `scenario_getTools_hang` (`test/webmcp_fake_cdp.py`). Tarayıcı gerekmez.
- `CDPILOT_TEST_ONLY='webmcp' node test/test.js`: 18 passed, 0 failed (e2e atlandı).

## Yalnız CI doğrular
- Gerçek Chrome'da asılı belge gerçekten bir `getTools()` sözü müydü, yoksa başka bir engel mi.
- 5 sn sınırı yavaş runner'da yeterli mi. Yetmezse list hata döner, `until` 30 sn içinde yeniden dener.
- Aynı hata tekrar çıkarsa mesaj artık hangi belgenin asıldığını değil yalnız "TimeoutError" der. Ayırt etmek için `facts.stuck` JSON çıktıya eklenebilir.
