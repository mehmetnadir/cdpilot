#!/usr/bin/env python3.13
"""json-bicim.py - cdpilot agent observe ve act diff çıktılarının JSON biçimlendirme maliyetini ölçer.

o200k_base tokenizer ile 4 biçim karşılaştırılır:
  (a) as printed: indent=2, ensure_ascii=True (varsayılan)
  (b) indent=2, ensure_ascii=False
  (c) compact separators (',', ':'), ensure_ascii=True
  (d) compact separators (',', ':'), ensure_ascii=False

Kullanım:
  /Users/nadir/01dev/_venvs/tiktoken/bin/python3.13 -I .claude/docs/olcum/json-bicim.py [--analyze] [--capture <site>|all]
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

try:
    import tiktoken
except ImportError:
    print("tiktoken bulunamadı! /Users/nadir/01dev/_venvs/tiktoken/bin/python3.13 kullanın.", file=sys.stderr)
    sys.exit(1)

SITES = [
    {
        "key": "hn",
        "label": "Hacker News",
        "url": "https://news.ycombinator.com/",
        "action_pref": ("textbox", "searchbox", "input"),
    },
    {
        "key": "enwiki",
        "label": "Wikipedia (EN)",
        "url": "https://en.wikipedia.org/wiki/Web_browser",
        "action_pref": ("searchbox", "textbox", "input"),
    },
    {
        "key": "mdn",
        "label": "MDN MutationObserver",
        "url": "https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver",
        "action_pref": ("searchbox", "textbox", "input"),
    },
    {
        "key": "trwiki",
        "label": "Wikipedia (TR)",
        "url": "https://tr.wikipedia.org/wiki/Web_tarayıcısı",
        "action_pref": ("searchbox", "textbox", "input"),
    },
    {
        "key": "jawiki",
        "label": "Wikipedia (JA)",
        "url": "https://ja.wikipedia.org/wiki/ウェブブラウザ",
        "action_pref": ("searchbox", "textbox", "input"),
    },
]

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "json-bicim"))
CDPILOT_BIN = "/Users/nadir/01dev/cdpilot/bin/cdpilot.js"


def run_cdpilot(cdpilot_home: str, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["CDPILOT_HOME"] = cdpilot_home
    env["CDPILOT_LOG"] = "0"
    env["CDPILOT_NO_AUTOLAUNCH"] = "1"
    env["CDPILOT_PYTHON"] = "/opt/homebrew/bin/python3.13"
    env["PATH"] = f"/opt/homebrew/bin:{env.get('PATH', '')}"

    cmd = ["node", CDPILOT_BIN] + args
    res = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return res.returncode, res.stdout, res.stderr


def capture_site(site: dict):
    site_key = site["key"]
    url = site["url"]
    os.makedirs(DATA_DIR, exist_ok=True)
    observe_file = os.path.join(DATA_DIR, f"observe-{site_key}.json")
    act_file = os.path.join(DATA_DIR, f"act-{site_key}.json")

    tmp_home = tempfile.mkdtemp(prefix="cdpilot-json-")
    print(f"[{site_key}] Başlatılıyor: {url} (tmp_home: {tmp_home})")
    try:
        # 1. Connect
        code, out, err = run_cdpilot(tmp_home, ["connect", "9333"])
        if code != 0:
            raise RuntimeError(f"connect başarısız ({code}): {err}")

        # 2. Go
        print(f"[{site_key}] 'go {url}' yürütülüyor...")
        t0 = time.time()
        code, out, err = run_cdpilot(tmp_home, ["go", url], timeout=180)
        dur = time.time() - t0
        print(f"[{site_key}] 'go' tamamlandı ({dur:.1f}s, exit {code})")
        if code != 0:
            print(f"[{site_key}] Uyarı: go exit code {code}: {err}", file=sys.stderr)

        # 3. Observe
        print(f"[{site_key}] 'agent observe' yürütülüyor...")
        code, out, err = run_cdpilot(tmp_home, ["agent", "observe"])
        if code != 0:
            raise RuntimeError(f"agent observe başarısız ({code}): {err}")
        with open(observe_file, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[{site_key}] observe kaydedildi: {observe_file} ({len(out)} bayt)")

        # Parse actions
        try:
            obs_data = json.loads(out)
        except Exception as e:
            raise RuntimeError(f"observe çıktısı JSON olarak okunamadı: {e}")

        actions = obs_data.get("actions", [])
        # cdpilot drops oldest 200 refs when len(amap) > 1000
        min_ref_num = 201 if len(actions) > 1000 else 1

        chosen_ref = None
        chosen_action = "fill"
        chosen_text = "test"

        for pref in site["action_pref"]:
            for a in actions:
                r_num = int(str(a.get("ref", "@0")).lstrip("@")) if str(a.get("ref", "@0")).lstrip("@").isdigit() else 0
                if r_num < min_ref_num:
                    continue
                role = a.get("role", "")
                tag = a.get("tag", "")
                name = str(a.get("name", "")).lower()
                if pref in role or pref in tag or pref in name:
                    chosen_ref = a.get("ref")
                    if "button" in role or "button" in tag:
                        chosen_action = "click"
                        chosen_text = None
                    break
            if chosen_ref:
                break

        # Fallback to button or any actionable ref
        if not chosen_ref:
            for a in actions:
                r_num = int(str(a.get("ref", "@0")).lstrip("@")) if str(a.get("ref", "@0")).lstrip("@").isdigit() else 0
                if r_num < min_ref_num:
                    continue
                role = a.get("role", "")
                if role == "button":
                    chosen_ref = a.get("ref")
                    chosen_action = "click"
                    chosen_text = None
                    break
                elif role in ("link", "tab"):
                    chosen_ref = a.get("ref")
                    chosen_action = "hover"
                    chosen_text = None
                    break

        if not chosen_ref:
            print(f"[{site_key}] Uyarı: Uygun etkileşim öğesi bulunamadı!", file=sys.stderr)
            with open(act_file, "w", encoding="utf-8") as f:
                json.dump({"error": "no suitable non-navigating action found"}, f)
        else:
            print(f"[{site_key}] 'agent act' ref={chosen_ref} action={chosen_action} yürütülüyor...")
            act_cmd = ["agent", "act", "--ref", chosen_ref, "--action", chosen_action]
            if chosen_text:
                act_cmd.extend(["--text", chosen_text])
            code, out, err = run_cdpilot(tmp_home, act_cmd, timeout=60)
            if code != 0:
                print(f"[{site_key}] Uyarı: act başarısız ({code}): {err}", file=sys.stderr)
            with open(act_file, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"[{site_key}] act kaydedildi: {act_file} ({len(out)} bayt)")

    finally:
        # Close own tabs
        run_cdpilot(tmp_home, ["close"])
        silinecek = os.path.expanduser("~/Silinecekler")
        os.makedirs(silinecek, exist_ok=True)
        dest = os.path.join(silinecek, os.path.basename(tmp_home))
        shutil.move(tmp_home, dest)
        print(f"[{site_key}] Temizlik tamamlandı ({dest})")


def analyze_file(path: str, enc) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    obj = json.loads(raw)

    s_a = json.dumps(obj, indent=2, ensure_ascii=True)
    # Sanity check: compare s_a against raw printed text
    sanity = (raw.strip() == s_a.strip())

    s_b = json.dumps(obj, indent=2, ensure_ascii=False)
    s_c = json.dumps(obj, separators=(",", ":"), ensure_ascii=True)
    s_d = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    res = {
        "file": os.path.basename(path),
        "sanity": sanity,
        "a_char": len(s_a),
        "a_tok": len(enc.encode(s_a)),
        "b_char": len(s_b),
        "b_tok": len(enc.encode(s_b)),
        "c_char": len(s_c),
        "c_tok": len(enc.encode(s_c)),
        "d_char": len(s_d),
        "d_tok": len(enc.encode(s_d)),
    }
    res["sav_tok_pct"] = round((res["a_tok"] - res["d_tok"]) / res["a_tok"] * 100, 2) if res["a_tok"] else 0.0
    res["sav_char_pct"] = round((res["a_char"] - res["d_char"]) / res["a_char"] * 100, 2) if res["a_char"] else 0.0
    return res


def run_full_analysis():
    enc = tiktoken.get_encoding("o200k_base")

    obs_list = []
    act_list = []

    for site in SITES:
        site_key = site["key"]
        label = site["label"]
        obs_p = os.path.join(DATA_DIR, f"observe-{site_key}.json")
        act_p = os.path.join(DATA_DIR, f"act-{site_key}.json")

        if os.path.exists(obs_p):
            r = analyze_file(obs_p, enc)
            r["label"] = label
            r["url"] = site["url"]
            obs_list.append(r)

        if os.path.exists(act_p):
            r = analyze_file(act_p, enc)
            r["label"] = label
            r["url"] = site["url"]
            act_list.append(r)

    return obs_list, act_list


def print_markdown_table(rows: list[dict], title: str):
    print(f"\n### {title}\n")
    headers = [
        "Sayfa",
        "Dosya",
        "(a) chars",
        "(a) tok",
        "(b) chars",
        "(b) tok",
        "(c) chars",
        "(c) tok",
        "(d) chars",
        "(d) tok",
        "Tasarruf (d vs a) %",
        "Sanity",
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        row = [
            f"[{r['label']}]({r['url']})",
            r["file"],
            f"{r['a_char']:,}",
            f"{r['a_tok']:,}",
            f"{r['b_char']:,}",
            f"{r['b_tok']:,}",
            f"{r['c_char']:,}",
            f"{r['c_tok']:,}",
            f"{r['d_char']:,}",
            f"{r['d_tok']:,}",
            f"**%{r['sav_tok_pct']:.2f}**",
            "✓" if r["sanity"] else "✗",
        ]
        print("| " + " | ".join(row) + " |")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", choices=[s["key"] for s in SITES] + ["all"])
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()

    if args.capture:
        targets = SITES if args.capture == "all" else [s for s in SITES if s["key"] == args.capture]
        for t in targets:
            capture_site(t)

    if args.analyze or not args.capture:
        obs, act = run_full_analysis()
        print_markdown_table(obs, "1. agent observe Çıktıları")
        print_markdown_table(act, "2. agent act (diff) Çıktıları")

        med_obs = statistics.median([r["sav_tok_pct"] for r in obs])
        med_act = statistics.median([r["sav_tok_pct"] for r in act])
        med_all = statistics.median([r["sav_tok_pct"] for r in obs + act])

        print(f"\n- **Medyan Tasarruf (observe)**: %{med_obs:.2f}")
        print(f"- **Medyan Tasarruf (act diff)**: %{med_act:.2f}")
        print(f"- **Genel Medyan Tasarruf**: %{med_all:.2f}")


if __name__ == "__main__":
    main()
