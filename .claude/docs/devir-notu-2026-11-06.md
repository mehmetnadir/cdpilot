# Devir notu — 06.11.2026 (Mac yeniden başlatma öncesi), oturum cdpilot / nadir-21

Nadir 06.11: "güvenlik ve performans ile ilgili yapacaklarımızı da atlamadan, CEO olarak projeyi yönet;
herkese görevlerini dağıt; restart sonrası devam et." Bu not restart sonrası ilk okunacak dosyadır.

## 1. Restart anındaki durum

| Alan | Durum |
|---|---|
| main | `227b24f` merge (`--tools core`) + `109486e` (MacAppCodeSignClone) + bu notun commit'i. origin'e push YOK (Nadir onayı). |
| npm | 0.9.4. 09.11 Pzt paylaşımı "sonraki sürüm `--tools core` ekliyor" diyor → 0.9.5 o güne kadar çıkmalı ya da metin değişmeli. |
| X hesabı | 3 takipçi. Editör her sabah 09:17 (`launchd com.conductor.x-editor`, Mac açıkken). Kuyruk: 06.11 Cum 17:23, 07.11 Cmt 14:07, 09.11 Pzt 17:17. Raporlar `~/.claude/canavar/x-editor/`. |
| srv21 bot | poster/cycle timer'ları canlı; dondurma yok; drafter'ın Claude kolu jetonsuz (Nadir yazacak). |
| Ultra Claude kotası | KAPALI → 10.11 13:25. `yargi`/`review` Gemini 3.8'e düşüyor. `kredi` rolü çalışıyor (org 1: 68 $/190 $). |

## 2. Geliştirme şeritleri (restart hepsini öldürür; worktree'deki dosyalar kalır)

| # | Şerit | Worktree / dal | İş dosyası (restart sonrası `-devam` sürümü) | Restart anı |
|---|---|---|---|---|
| 1 | Shadow DOM (#3) | `~/01dev/_worktrees/cdpilot-shadow` / `lane/shadow` | `.claude/docs/seritler-2026-11-06/serit-shadow-devam.json` | koşuyordu (12:21'den beri) |
| 2 | record/replay (#5) | `cdpilot-flow` / `lane/flow` | `serit-flow-devam.json` | koşuyordu |
| 3 | HAR export (#4) | `cdpilot-har` / `lane/har` | `serit-har-devam.json` | koşuyordu |
| 4 | X poster uzunluk ön kontrolü | `cdpilot-xbot` / `lane/xbot` | `serit-xbot-devam.json` | koşuyordu |
| 5 | Vaat denetimi (salt okunur) | ana depo | `serit-iddia-devam.json` | koşuyordu; çıktı `~/.claude/canavar/agy-filo/20261106-122147/iddia-denetimi.d1.out` (bittiyse) |
| 6 | Kırık test `bot-auth: idle close counts CDP clients…` | `cdpilot-botauth` / `lane/botauth` | spec YOK (aşağıda kök neden ipuçları) | tam test koşusu bitti: 563 geçti, 2 arıza |

Yeniden başlatma komutu (her şerit kendi worktree'sinden, arka planda):
`cd <worktree> && agy-filo run /Users/nadir/01dev/cdpilot/.claude/docs/seritler-2026-11-06/serit-<ad>-devam.json --es 1`
Önce `~/.claude/canavar/agy-filo/20261106-1221*/` özetlerine bak: bitmiş şeridi yeniden koşturma (hesaplamadan önce 3 soru).

Birleştirme sırası: önce diff satır satır okunur (Gemini raporu kanıt değildir), tam paket `node test/test.js`
(≈4 dk) boş makinede koşar, `test-tutanak kos` ile TT kimliği alınır, sonra `git merge --no-ff lane/<ad>`.
Hepsi `src/cdpilot.py`'ye dokunur; çatışma olursa küçük olur (ayrı fonksiyonlar).

### Şerit 6 kök neden ipuçları
- Arıza: `a connected client is seen: false !== true` → `test/bot_auth_fake_cdp.py:611 sc_clients`, `live.child_seen`.
- Kod: `_cdp_client_pids` (`src/cdpilot.py` ~2556) macOS'ta `netstat -anv -p tcp` + `_cdp_client_pids_bsd_netstat`.
- Elle sonda (06.11, bu Mac): basit Python istemci için netstat satırı `tcp4 0 0 127.0.0.1.60872 127.0.0.1.60873
  ESTABLISHED 0 0 132792 132792 Python:95578 …` → ayrıştırıcı bunu çözer. Yani arıza ya yarışta (çocuk `up` yazdıktan
  sonra netstat 5 sn `timeout` ile dolu makinede geç kalıyor → None → `tool:false` olurdu, ama test `tool:true` dedi),
  ya çocuk sürecin pid/isim sütununda (`sys.executable` = Xcode python'u "Python" adı; uzun ad boşluklu olabilir:
  "Google Chrome H:303" örneği fixture'da var) ya da sütun kaymasında. Spec yazmadan önce `sc_clients`'ı tek başına
  koştur ve netstat çıktısını dosyaya yazdır.
- İkinci arıza `press hold (fake CDP): CDPILOT_PRESS_MS=0-0…` zamanlama testi; 5 paralel ajan yük altında
  (medyan 15 ms sınırı, ölçülen 0,4–199 ms). Boş makinede yeniden koş; geçerse yük kaynaklı say.

## 3. CEO planı (restart sonrası kurulacak; güvenlik ve performans dahil)

| Kol | İş | Kim | Kapı / ölçüm |
|---|---|---|---|
| Ürün | #3 shadow DOM · #5 record/replay · #4 HAR · sonra `browser_flow` MCP aracı, Faz 3 `agent observe/act` | agy-filo `kod` (Gemini) · spec + inceleme şef | test/test.js + CHANGELOG + README; diff satır satır |
| Kalite | kırık `bot-auth` testi · yük altında kırılan zamanlama testleri · CI e2e | agy-filo `kod` | 565/565, TT kimliği |
| Güvenlik | T0 `guvenlik-smoke.sh` (npm audit, sır taraması, sessiz catch) her sürüm öncesi · T1 `security-review` skill'i 0.9.5 diff'ine (şef, Claude) · T2 tam denetim: cdpilot npm CLI + srv21 botu için `security-audit` (16 ajan) — Nadir kararı · srv21 bot: çerez dosyası izinleri, `cookies-snapshot.json` yaşam süresi | şef + skill | `canavar/guvenlik-smoke.jsonl`; bulgular `.claude/docs/guvenlik-*.md` |
| Performans | ölçüm tabanı: komut gecikmesi (launch, go, click, screenshot), MCP şema token'ı (5.769 → 1.342 ölçüldü), bellek; a11y-snapshot token iddiası satılmaz (27.09 ölçümü) · `eval-batch` "5-30x" iddiası yeniden ölçülür | agy-filo `kod` ölçüm betiği; şef yorumlar | `.claude/docs/perf-taban-<tarih>.md`, sayılar README'ye ancak ölçümle |
| Vaat | 5. şerit raporu → YANLIŞ/BAYAT iddialar düzeltilir, KANITLI olanlara test kapısı | şef | `test/test.js` claim gates, site `claims.test.mjs` |
| Büyüme | X editörü günlük tur (kredi) · Show HN / Reddit (Nadir hesabı) · demo GIF + sabit tweet | editör + şef | `kpi.jsonl` (takipçi, görüntü) |
| Sürüm | 0.9.5: şeritler + CHANGELOG sürümleme + T0 + T1 → push + PR + npm (Nadir onayı) | şef | tutanak + smoke |

## 4. Nadir'e (karar / yetki)
1. 0.9.5 için push + PR + npm onayı (Pzt 09.11'e kadar).
2. srv21 `state/claude-oauth-token` (0 bayt, 28.09'dan beri): drafter'ın Claude kolu ve 3 bot işi `exit=1`.
3. Show HN / Reddit çapraz paylaşım: Nadir'in hesabı gerekli.
4. T2 tam güvenlik denetimi (16 ajan, ~45 dk) ne zaman: ilk 1.0 öncesi mi, şimdi mi?
