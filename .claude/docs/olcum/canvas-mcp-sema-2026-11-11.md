# Canlı Tuval MCP Araçları Şema Token Ölçümü (11.11.2026)

Dayanak: PRD §8 S4 (`plan-canli-tuval.md`), jüri koşulu C2 (`CORE_TOOLS` dışı).

## Ölçüm Koşulları

| Alan | Değer |
|---|---|
| Tarih | 11.11.2026 |
| Donanım / İS | Apple M1 Max (`arm64`), macOS |
| Yük (`uptime`) | `0:41  up 6 days, 13:42, 2 users, load averages: 201.41 151.35 114.07` |
| Serileştirme | `json.dumps(obj, ensure_ascii=False, separators=(",", ":"))` (kompakt JSON) |
| Tokenizer | `chars / 4` ve `tiktoken 0.12.0` (`o200k_base`, `cl100k_base` — yerel `arm64` Python) |

## 1. Araç Başına Şema Maliyeti (`CANVAS_TOOLS`)

| Araç | Karakter (kompakt JSON) | `chars / 4` (tavan) | `o200k_base` | `cl100k_base` |
|---|---:|---:|---:|---:|
| `browser_canvas_set` | 484 | 121 (121,00) | 111 | 111 |
| `browser_canvas_patch` | 460 | 115 (115,00) | 112 | 112 |
| `browser_canvas_events` | 718 | 180 (179,50) | 201 | 198 |
| **`CANVAS_TOOLS` dizisi toplamı** | **1.666** | **417 (416,50)** | **426** | **421** |

## 2. `tools/list` Profil Etkisi (`CDPILOT_WEBMCP=0`)

| Profil | Araç Sayısı | Karakter | `chars / 4` | `o200k_base` | Fark (`o200k_base`) |
|---|---:|---:|---:|---:|---:|
| Varsayılan (`all`) — tuval öncesi | 49 | 29.793 | 7.449 | 6.443 | — |
| Varsayılan (`all`) — tuval sonrası | 52 | 31.458 | 7.865 | 6.867 | **+424** (+%6,6) |
| Çekirdek (`--tools core`) | 11 | 6.294 | 1.574 | 1.356 | **+0** (%0,0) |

## 3. Notlar (Değişiklik Notu İçin Özet)

- Üç canlı tuval MCP aracı (`browser_canvas_set`, `browser_canvas_patch`, `browser_canvas_events`) kompakt JSON olarak toplam **1.666 karakter** (**417** `chars/4`, **426** `o200k_base` token) tutar.
- Varsayılan `all` profilinde `tools/list` çıktısı **+1.665 karakter / +424 `o200k_base` token** büyür (49 → 52 araç).
- `--tools core` (`CDPILOT_MCP_TOOLS=core`) profilinde üç araç `CORE_TOOLS` dışında kaldığı için `tools/list` maliyeti **+0 token** olur; istemci gerekirse `browser_tools` (`action="enable"`) ile etkinleştirir.
