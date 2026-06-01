# Manual smoke test — `cdpilot watch`

Sanity check the new continuous-screencast feature end-to-end against a real
local `<video>` element. Unit tests cover wiring and parsing; this exercises
the actual CDP screencast loop, ring buffer, and query time mapping.

## Prereqs

- Brave / Chrome / Chromium installed (cdpilot auto-detects)
- A short local MP4 file. If you don't have one, generate a 10-second test
  pattern with ffmpeg:

  ```bash
  ffmpeg -f lavfi -i testsrc=duration=10:size=640x360:rate=30 \
         -pix_fmt yuv420p /tmp/cdpilot-sample.mp4
  ```

- Optional: a minimal HTML wrapper around the video so autoplay works
  (file:// URLs can play local videos directly in Chromium):

  ```bash
  cat >/tmp/cdpilot-watch.html <<'EOF'
  <!doctype html><meta charset="utf-8">
  <title>cdpilot watch smoke</title>
  <style>body{margin:0;background:#000}video{width:100vw;height:100vh}</style>
  <video src="/tmp/cdpilot-sample.mp4" autoplay muted playsinline controls></video>
  EOF
  ```

## Steps

1. **Launch the browser** (if not already running for this project):

   ```bash
   npx cdpilot launch
   ```

2. **Start watching** the local video. The command returns immediately;
   the daemon runs in the background:

   ```bash
   npx cdpilot watch start file:///tmp/cdpilot-watch.html --fps=10
   ```

   Expected output (JSON):

   ```json
   {
     "ok": true,
     "pid": 12345,
     "url": "file:///tmp/cdpilot-watch.html",
     "fps": 10,
     ...
     "frames_dir": "/Users/you/.cdpilot/projects/<id>/watch/frames"
   }
   ```

3. **Let it record for ~6 seconds**, then check status:

   ```bash
   sleep 6 && npx cdpilot watch status
   ```

   Expected: `running: true`, `frames: 50-60` (10fps × 6s), `disk_mb > 0`.

4. **Query a time window** around the 3-second mark (2.5 → 3.5):

   ```bash
   npx cdpilot watch query --at 0:03 --window 1s --max 8
   ```

   Expected: `count` between 5 and 10, `duration_s ≈ 1`, and each path in
   `frames` should exist and be a valid JPEG (`file <path>` will say
   "JPEG image data").

5. **Query the last 2 seconds** of capture:

   ```bash
   npx cdpilot watch query --last 2s --max 8
   ```

6. **Open one of the JPEGs** to eyeball that we actually captured the
   test pattern animating:

   ```bash
   open "$(npx cdpilot watch query --last 1s --max 1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["frames"][0])')"
   ```

7. **Stop and cleanup**:

   ```bash
   npx cdpilot watch stop
   ```

   Expected: `killed: true`, `frames_removed: <count>`.

8. **Verify cleanup**:

   ```bash
   npx cdpilot watch status
   # → running: false, frames: 0
   ```

## What you're checking

| Check | Why it matters |
|---|---|
| Status confirms `running: true` within ~2s of `start` | Daemon actually attached and started screencast (not just spawned then died) |
| Frame count grows ~10/sec at `--fps=10` | `everyNthFrame` math and ACK loop are healthy |
| `--at 0:03` returns frames whose timestamps cluster around screencast_start + 3s | Video-time → wall-clock mapping works |
| JPEGs open and show animation | ACK loop isn't dropping frames; quality param actually wired |
| `stop` deletes frames | Ring buffer cleanup works |

## Known limitations / risk notes

- **DRM-protected video** (Netflix, Spotify Web, etc.) renders to a separate
  hardware path that does NOT appear in CDP screencasts. Captured frames
  will be black where the video is. Documented; not a bug we can fix.
- **`file://` vs `http(s)://`**: identical behavior for the screencast
  itself, but `file://` cannot use cookies or service workers. For
  smoke-testing that's fine; for real videos behind auth, use http(s).
- **Cross-origin iframes**: the screencast captures the top-level frame
  composition, so iframe content shows up visually but you can't seek
  it via the autoplay JS (which only finds `document.querySelector('video')`
  in the main frame).
- **`Page.startScreencast` is renderer-process** — if the page hard-crashes
  the daemon will keep running but emit no frames. `watch status` reports
  `running: true` but `frames` count stops growing — easy to detect.
- **Two concurrent watches on the same target** would race. `watch start`
  is idempotent — it kills any prior daemon before starting a new one.
