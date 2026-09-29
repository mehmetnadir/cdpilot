# chrome-for-testing

This example demonstrates downloading and setting up Chrome for Testing (`cdpilot browser install chrome-for-testing`), registering an unpacked dev extension (`cdpilot ext-install`), selecting Chrome for Testing as the target browser (`cdpilot browser chrome-for-testing`), verifying the content script marker in page DOM via `eval`, and checking status with `cdpilot browser status`.

## Commands

```bash
cdpilot browser install chrome-for-testing
cdpilot ext-install ../../test/fixtures/extension/unpacked
cdpilot browser chrome-for-testing
cdpilot go http://127.0.0.1:59924/index.html
cdpilot eval "document.documentElement.dataset.cdpilotExt"
cdpilot browser status
cdpilot shot output/screenshot.png
cdpilot stop
```

## Captured Output

```text
$ cdpilot browser install chrome-for-testing
Downloading https://storage.googleapis.com/chrome-for-testing-public/154.0.8037.57/mac-arm64/chrome-mac-arm64.zip (191.4 MB)
Downloaded 191429663 bytes (size verified; md5 verified; sha256 0e6b3439469c1b8b95b2e89c72ea29f7af00fb2c28a8878358a0b6002b6d3a64)
Chrome for Testing 154.0.8037.57 (mac-arm64): <tmp>/home/browsers/chrome-for-testing/154.0.8037.57/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
  For extension development and testing (it loads unpacked extensions; Chrome 137+ does not). Not a stealth browser.
  Used instead of Chrome while dev extensions are registered; select it always with: cdpilot browser chrome-for-testing
$ cdpilot ext-install ../../test/fixtures/extension/unpacked
No browser process found (port 59925).
✅ Dev extension registered: cdpilot e2e fixture (v1.0.0)
   Path: <repo>/test/fixtures/extension/unpacked
   Restarting browser...
Launching browser (isolated session, port 59925) [chrome-for-testing-86c0e7]...
  Dev extensions: 1
  Mode: headless
  Idle close: off (launch --idle-close <min> or CDPILOT_IDLE_CLOSE=<min> turns it on)
CDP ready! (port 59925) [chrome-for-testing-86c0e7]
$ cdpilot browser chrome-for-testing
Browser preference: chrome-for-testing
Restart the browser (`cdpilot stop` then any command) for the change to take effect.
$ cdpilot go http://127.0.0.1:59924/index.html
  Dev extension injected: cdpilot e2e fixture/content.js
Chrome for Testing Demo

Extension test page
$ cdpilot eval "document.documentElement.dataset.cdpilotExt"
loaded:gldenfmenfgojdmdmnnocjgbdjeflelc
$ cdpilot browser status
Preference:  chrome-for-testing
  resolved:  <tmp>/home/browsers/chrome-for-testing/154.0.8037.57/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
Auto-pick:   <tmp>/home/browsers/chrome-for-testing/154.0.8037.57/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
  reason:    extension mode (registry has dev extensions) + macOS 26 (Brave demoted)
  order:     vivaldi > brave > edge > chromium > chrome
Installed:   brave, chrome, vivaldi, chrome-for-testing
Dev exts:    1 registered (run `cdpilot extensions` to list)
Chrome for Testing: 154.0.8037.57 (mac-arm64)
  path:      <tmp>/home/browsers/chrome-for-testing/154.0.8037.57/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
  use:       replaces Chrome while dev extensions are registered; extension development/testing, not stealth
$ cdpilot shot output/screenshot.png
output/screenshot.png (10.2KB)
$ cdpilot stop
  Closed via CDP Browser.close.
Browser stopped (port 59925).
```
