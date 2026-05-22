#!/usr/bin/env bash
# Mac Vivaldi'de doğrudan JavaScript ile post — cdpilot bypass
set +e

PY=/opt/homebrew/bin/python3.13
CDPILOT=/Users/nadir/01dev/cdpilot/src/cdpilot.py

CONTENT='webdriver was designed for cross-browser testing in 2011. cdp was designed to build devtools. one is for compliance, the other for deep surgical control of the engine. different tools, different problems'

echo "→ Navigate to compose..."
"$PY" "$CDPILOT" go https://x.com/compose/post
sleep 4

echo "→ Type content + click post..."
"$PY" "$CDPILOT" eval "
(async () => {
  const ta = document.querySelector('[data-testid=tweetTextarea_0]');
  if (!ta) return {error: 'no textarea'};
  ta.focus();
  // execCommand text insertion
  document.execCommand('insertText', false, $(echo -n "$CONTENT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'));
  // Wait button to enable
  await new Promise(r => setTimeout(r, 1500));
  const btn = document.querySelector('[data-testid=tweetButton]') || document.querySelector('[data-testid=tweetButtonInline]');
  if (!btn) return {error: 'no button'};
  if (btn.getAttribute('aria-disabled') === 'true') return {error: 'button disabled', text: ta.innerText};
  btn.click();
  await new Promise(r => setTimeout(r, 5000));
  return {url: location.href, text: ta.innerText ? 'still in compose' : 'posted'};
})()
"
echo
sleep 3
echo "→ Final URL check..."
"$PY" "$CDPILOT" eval "location.href"
