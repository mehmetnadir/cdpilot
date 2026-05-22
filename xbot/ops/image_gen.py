#!/usr/bin/env python3
"""image_gen.py — fal.ai gpt-image-2 + signature "Field Notebook" style.

ONE signature style only (xbot/image-styles.md). Logo + @cdpilot_dev watermark
composited in bottom-right post-process so it's pixel-perfect every time
(never trust AI to render text/logos consistently).

Env:
  FAL_KEY              required — loaded from ~/cdpilot-twitter-data/fal.env
  FAL_IMAGE_MODEL      default: fal-ai/gpt-image-2/text-to-image
  CDPILOT_XBOT_DATA    default: ~/cdpilot-twitter-data

CLI:
  python image_gen.py gen --id post-001 --content "..." [--title "..."]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont  # type: ignore

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
IMAGES_DIR = DATA / "images"
LOG_FILE = DATA / "logs" / "image-gen.log"
FAL_ENV = DATA / "fal.env"
FAL_QUEUE = "https://queue.fal.run"
LOGO_PNG = DATA / "logo-256.png"


SIGNATURE_PROMPT = """A flat-lay top-down photo of an open Moleskine-style notebook with cream
textured paper (color #f4ebd6). Hand-pencilled title in graphite at the top
reads "{title}". Below the title, {content}. On the desk around the notebook:
a small ceramic mug with a faint coffee ring stain, a paper clip, a sharpened
wooden pencil. Soft afternoon light from the upper-left window. Shot on a
50mm lens, slight depth of field on the corners. Color grade: warm, slightly
desaturated, magazine editorial photography. The bottom-right quadrant of
the image is intentionally empty (clear table surface) — leave at least 18%
of the bottom-right corner free of objects. Color palette: cream paper,
graphite pencil, single amber (#f5a623) accent. NOT a 3D render. NOT digital
art. NOT vector. NOT AI-style glossy. Photo-realistic, analog feel."""


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _load_fal_key() -> tuple[str, str]:
    env: dict[str, str] = {}
    if FAL_ENV.exists():
        for line in FAL_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    key = os.environ.get("FAL_KEY") or env.get("FAL_KEY")
    model = (os.environ.get("FAL_IMAGE_MODEL") or env.get("FAL_IMAGE_MODEL")
             or "fal-ai/gpt-image-2")
    if not key:
        sys.exit(f"FAL_KEY missing — set in env or {FAL_ENV}")
    return key, model


def _http(url: str, method: str = "GET", *, key: str, body: dict | None = None,
          timeout: int = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Key {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        raise RuntimeError(f"fal API {method} → {e.code}: {msg[:400]}")


def _download(url: str, dst: Path, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cdpilot-image-gen/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dst.write_bytes(r.read())


def _composite_watermark(image_path: Path) -> None:
    """Stamp logo + @cdpilot_dev (only) in bottom-right corner.

    Panel sized dynamically to the rendered text width so the handle never
    clips. Logo on the left, single-line handle on the right.
    """
    base = Image.open(image_path).convert("RGBA")
    W, H = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    pad = int(min(W, H) * 0.028)
    handle = "@cdpilot_dev"

    # Choose font + size: ~5% of min dimension for the handle
    target_size = max(22, int(min(W, H) * 0.045))
    font_handle = None
    for font_path in [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    ]:
        try:
            font_handle = ImageFont.truetype(font_path, target_size)
            break
        except OSError:
            continue
    if font_handle is None:
        font_handle = ImageFont.load_default()

    # Measure text
    tmp_img = Image.new("RGBA", (10, 10))
    tmp_draw = ImageDraw.Draw(tmp_img)
    bbox = tmp_draw.textbbox((0, 0), handle, font=font_handle)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    logo_size = int(target_size * 1.6)
    inner_pad = int(target_size * 0.5)
    gap = int(target_size * 0.45)
    panel_w = inner_pad + logo_size + gap + text_w + inner_pad
    panel_h = max(logo_size, text_h) + int(target_size * 0.55)

    panel_x = W - panel_w - pad
    panel_y = H - panel_h - pad

    # Semi-translucent cream panel
    draw.rounded_rectangle(
        [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
        radius=int(panel_h * 0.22),
        fill=(250, 250, 250, 210),
    )

    # Logo (left)
    logo_x = panel_x + inner_pad
    logo_y = panel_y + (panel_h - logo_size) // 2
    if LOGO_PNG.exists():
        logo = Image.open(LOGO_PNG).convert("RGBA")
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
        overlay.paste(logo, (logo_x, logo_y), logo)

    # Handle (right, vertically centered)
    text_x = logo_x + logo_size + gap
    text_y = panel_y + (panel_h - text_h) // 2 - bbox[1]
    draw.text((text_x, text_y), handle,
              fill=(58, 56, 53, 255), font=font_handle)

    composited = Image.alpha_composite(base, overlay).convert("RGB")
    composited.save(image_path, format="PNG", optimize=True)
    _log(f"watermarked {image_path.name}")


def generate(image_id: str, content: str, *, title: str | None = None,
             size: str = "1024x1024", quality: str = "standard",
             model: str | None = None) -> dict:
    """Generate one signature-style image + composite watermark."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    key, default_model = _load_fal_key()
    endpoint = model or default_model
    final_title = title or "cdpilot · field notes"
    prompt = SIGNATURE_PROMPT.format(title=final_title, content=content.strip())

    started = time.time()
    submit_url = f"{FAL_QUEUE}/{endpoint}"
    # gpt-image-2 schema: image_size is an object (width/height), quality is enum
    if "x" in str(size):
        w, h = size.lower().split("x")
        size_obj = {"width": int(w), "height": int(h)}
    else:
        size_obj = {"width": 1024, "height": 1024}
    quality_norm = {"standard": "medium", "hd": "high"}.get(quality, quality)
    if quality_norm not in ("auto", "low", "medium", "high"):
        quality_norm = "medium"
    payload = {"prompt": prompt, "image_size": size_obj, "quality": quality_norm}
    _log(f"submit {image_id} → {endpoint} (size={size}, quality={quality})")
    submit_resp = _http(submit_url, "POST", key=key, body=payload, timeout=60)
    req_id = submit_resp.get("request_id") or submit_resp.get("id")
    if not req_id:
        raise RuntimeError(f"no request_id in submit response: {submit_resp}")

    # fal returns status_url + response_url (status strips /text-to-image suffix);
    # always prefer these over hand-built URLs.
    status_url = submit_resp.get("status_url") or f"{FAL_QUEUE}/{endpoint}/requests/{req_id}/status"
    result_url = submit_resp.get("response_url") or f"{FAL_QUEUE}/{endpoint}/requests/{req_id}"
    for attempt in range(120):
        time.sleep(2 if attempt < 5 else 5)
        st = _http(status_url, "GET", key=key, timeout=30)
        if st.get("status") == "COMPLETED":
            break
        if st.get("status") in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"fal request {req_id} {st.get('status')}: {st}")
    else:
        raise RuntimeError(f"fal request {req_id} timeout after 10min")

    result = _http(result_url, "GET", key=key, timeout=30)
    images = result.get("images") or result.get("data", {}).get("images") or []
    if not images:
        raise RuntimeError(f"no images in result: {result}")
    img = images[0]
    img_url = img.get("url") if isinstance(img, dict) else img
    dst = IMAGES_DIR / f"{image_id}.png"
    _download(img_url, dst)
    _composite_watermark(dst)
    elapsed = round(time.time() - started, 1)
    _log(f"✓ {image_id} → {dst} ({elapsed}s)")
    return {"id": image_id, "path": str(dst), "url": img_url, "elapsed_s": elapsed}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s_gen = sub.add_parser("gen", help="generate a signature-style image")
    s_gen.add_argument("--id", required=True)
    s_gen.add_argument("--content", required=True,
                       help="brief content description for the notebook scene")
    s_gen.add_argument("--title", default=None,
                       help="hand-pencilled title at top (default: 'cdpilot · field notes')")
    s_gen.add_argument("--size", default="1080x1080",
                       help="WxH (default 1080x1080 = X-safe 1:1). For mobile-dominant 4:5 use 1080x1350.")
    s_gen.add_argument("--quality", default="standard")
    s_gen.add_argument("--model")
    s_wm = sub.add_parser("watermark", help="apply watermark only (debug)")
    s_wm.add_argument("path")
    args = p.parse_args()

    if args.cmd == "gen":
        out = generate(args.id, args.content, title=args.title,
                       size=args.size, quality=args.quality, model=args.model)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "watermark":
        _composite_watermark(Path(args.path))
        print(json.dumps({"path": args.path, "watermarked": True}))


if __name__ == "__main__":
    main()
