"""Held-out injection measurement. Run: python3.13 -I .claude/docs/olcum/enjeksiyon-heldout.py [--json]"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("cdpilot_mod", ROOT / "src" / "cdpilot.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["cdpilot_mod"] = mod
spec.loader.exec_module(mod)

data = json.loads((ROOT / "test" / "fixtures" / "injection-heldout.json").read_text("utf-8"))


def scan(text: str) -> tuple[bool, str]:
    r = mod._agent_injection_scan([{"name": {"value": text}, "ignored": False}])
    return (bool(r), r[0]["match"] if r else "")


res: dict[str, list[dict[str, object]]] = {}
for grp in ("injected", "clean", "quoted"):
    res[grp] = []
    for it in data[grp]:
        f, m = scan(it["text"])
        res[grp].append({"family": it["family"], "text": it["text"], "flagged": f, "match": m})

if "--json" in sys.argv:
    print(json.dumps(res, ensure_ascii=False, indent=1))
else:
    for grp in res:
        n = sum(1 for r in res[grp] if r["flagged"])
        print(f"== {grp}: flagged {n}/{len(res[grp])}")
        for r in res[grp]:
            print(f"  [{'X' if r['flagged'] else '.'}] {r['family']:16} {r['match']:14} {str(r['text'])[:90]!r}")
