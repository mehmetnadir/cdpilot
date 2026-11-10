# Soak: "Could not get coordinates" teşhisi (11.11.2026)

| Madde | Sonuç |
|---|---|
| Hata | cli_fresh, her 27. çağrıda `agent act --ref @N` → `Could not get coordinates for @N.` |
| Kök neden | **Harness hatası.** Üç mod aynı cwd'de koşar. Aynı cwd = aynı proje = aynı sekme + aynı `agent-state.json` + aynı `a11y-refs.json`. |
| Ürün hatası mı | Hayır. Ürün hatası yalnız mesajın belirsizliği (düzeltildi). |
| Düzeltme | `soak.js`: her moda ayrı cwd. `src/cdpilot.py`: net hata mesajı. |
| Test | `agent act on a stale ref (fake browser)` → `CDPILOT_TEST_ONLY='agent'`: 23 passed, 0 failed |

## Neden her 3. çağrı, neden yalnız fresh

- Döngü sırası: cli_warm, mcp_warm, cli_fresh. Fresh payı `N_FRESH/N_WARM` ≈ 0.3: fresh her ~3,3 turda bir koşar.
- Fresh `observe` ile `act` arasında warm ve mcp 3 tur koşar. Bu turlar `go` içerir (op 0, her 9 turda bir).
- `go` ortak sekmeyi başka sayfaya götürür. Fresh'in ref'i eski belgenin düğümüne işaret eder.
- `agent-state.json` eski ref'i hâlâ tutar → "Unknown ref" çıkmaz. `DOM.getBoxModel` boş döner → "Could not get coordinates".
- Warm modlarda `observe` ile `act` arasına `go` girmez. Hata çıkmaz.
- Periyot 27 = 9 işlem × 3 sayfa: fresh'in `observe`→`act` aralığına düşen `go`, 27 çağrıda bir döngüsel olarak denk gelir (6, 33, 60 …).
- Kod: `cmd_click_ref` (src/cdpilot.py ~15926) ref'i `a11y-refs.json` dosyasından çözer. Dosya proje başına tektir.

## Yeniden üretim (paylaşılan Chrome 9333, geçici CDPILOT_HOME, CDPILOT_DAEMON=0)

Tek cwd'de, ayrı süreçler, aynı sekme:
```
go button.html ; agent observe          # ref @246 (button sayfası)
go links.html                           # başka mod sekmeyi götürdü
agent act --ref @246
ÖNCE:  Error: Could not get coordinates for @246.
SONRA: Error: Could not get coordinates for @246. The element is not in the current page
       (stale ref: the page changed since the last snapshot). Run 'agent observe' ... again ...
```
Tam round (go, content, eval, tabs, observe, act, diff, click, fill) tek başına 4 turda 0 hata verdi: ürün tek süreçte doğru çalışır.

Ayrı cwd (harness düzeltmesi), aynı Chrome:
```
cwdA: go button.html ; agent observe    # ref @2
cwdB: go links.html ; agent observe     # başka modun sekmesi
cwdA: agent act --ref @2                # exit 0, A'nın sekmesi hâlâ button.html
```

## Değişen dosyalar

- `.claude/docs/olcum/soak.js`: `modeCwd` (3 dizin), her cwd'de `connect 9333`, `runCli` / daemon / MCP kendi cwd'sinde.
- `src/cdpilot.py`: `cmd_click_ref` hata mesajı "stale ref" ipucu verir.
- `test/connect_fake_cdp.py`: `backendNodeId >= 9000` kutusuz düğüm (eski belge taklidi).
- `test/test.js`: yeni test. Eski `agent` testleri etkilenmedi (23/23).

## Kalan

- `hover` ve `submit` bayat ref'te sessiz geçer (hata vermez). Ayrı iş.
- soak.js yeniden koşulmadı (yük ve paylaşılan Chrome). Yeni koşuda cli_fresh `agent_act` hatası 0 beklenir. Doğrulama koşuyu yapan ajanda.
- Warm daemon + MCP aynı CDPILOT_HOME'u paylaşır. Proje kimliği cwd'den türer; cwd ayrımı yeterli görünür ama tam soak ile doğrulanmadı.
