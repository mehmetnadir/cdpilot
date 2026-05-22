#!/usr/bin/env python3
"""
Day 1 morning routine — manuel ilk run.
3 günlük rolling queue üretir: 2026-05-19, 2026-05-20, 2026-05-21.
"""
import json, os, uuid, random
from datetime import date, datetime, timedelta

random.seed(20260519)

DATA_DIR = os.path.expanduser('~/cdpilot-twitter-data')
QUEUE_DIR = os.path.join(DATA_DIR, 'queue')
os.makedirs(QUEUE_DIR, exist_ok=True)

LAUNCH = date(2026, 5, 19)
TODAY = date.today()
TZ = '+03:00'

def iso(d, hh, mm=0):
    return f'{d.isoformat()}T{hh:02d}:{mm:02d}:00{TZ}'

def gauss_jitter(target_hh, sigma_min=12):
    """Gaussian jitter around target hour, returns (hh, mm)."""
    offset = int(random.gauss(0, sigma_min))
    offset = max(-25, min(25, offset))
    total_min = target_hh * 60 + offset
    return total_min // 60, total_min % 60

def post(content, scheduled_time, tags=None, thread=None, humanizer_seed=None,
         quote_url=None, poll=None, media=None, long_form=False):
    item = {
        'id': str(uuid.uuid4()),
        'type': 'thread' if thread else 'post',
        'scheduled_time': scheduled_time,
        'status': 'pending',
        'content': content if not thread else None,
        'thread': thread,
        'reply_to': None,
        'result_url': None,
        'error': None,
        'humanizer_seed': humanizer_seed or random.randint(1, 99999),
        'carry_over': False,
        'tags': tags or [],
    }
    if long_form:
        item['long_form'] = True
    if quote_url:
        item['quote_url'] = quote_url
    if poll:
        item['poll'] = poll
    if media:
        item['media'] = media
    return item

# ─── Day 1 (2026-05-19) — Salı ─────────────────────────────────────────────
# day-001.md → T1 Foundations: CDP WebSocket session init (5-tweet thread)
day1_date = LAUNCH

day1_mid_h, day1_mid_m = gauss_jitter(14)
day1_hook_h, day1_hook_m = gauss_jitter(17)
day1_eve_h, day1_eve_m = gauss_jitter(21)

# Mid-day 14:00 — Tweet 2/5 (humanizer: lowercase başlangıç + period removal)
mid_content = (
    "webdriver was designed for cross-browser testing in 2011. "
    "cdp was designed to build devtools. one is for compliance, the other for deep surgical control of the engine. "
    "different tools, different problems"
)

# Hook 17:00 — Tweet 1/5 (TEMİZ — credibility için humanizer minimal)
hook_content = (
    "Most devs think \"automation\" and think Selenium or Playwright. "
    "But they're just wrappers for wrappers. "
    "Underneath is a WebSocket talking JSON-RPC to a browser process. "
    "It's raw, fast, and how things actually work. Ever looked at the raw frames?"
)

# Evening 21:00 — Thread (3 tweets, Tweet 3+4+5 birleşik)
evening_thread = [
    'when you connect, you send a JSON message: {"id":1,"method":"Target.getTargets"}. '
    'the browser responds with a list of tabs. no driver binary, no version mismatch, no java middleman',
    "cdpilot connects directly to the WebSocket URL. this removes the latency of a driver server and "
    "gets us events the second they happen in the renderer. poll vs push — not even close",
    "most automation tools hide this from you. we dont.\n\n"
    "source: https://github.com/nadirabbas/cdpilot"
]

day1_queue = {
    'date': day1_date.isoformat(),
    'day_n': 1,
    'track': 'T1 Foundations',
    'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    'generated_by': 'cowork',
    'posts': [
        post(mid_content, iso(day1_date, day1_mid_h, day1_mid_m),
             tags=['educational', 'mid-day']),
        post(hook_content, iso(day1_date, day1_hook_h, day1_hook_m),
             tags=['hook', 'credibility']),
        post(None, iso(day1_date, day1_eve_h, day1_eve_m),
             tags=['evening', 'thread', 'educational'],
             thread=evening_thread),
    ]
}

# ─── Day 2 (2026-05-20) — Çarşamba ─────────────────────────────────────────
# day-002.md → T2 Anti-Bot Wars: UA spoofing (zinger format, 1-tweet)
day2_date = LAUNCH + timedelta(days=1)
day2_mid_h, day2_mid_m = gauss_jitter(14)
day2_hook_h, day2_hook_m = gauss_jitter(17)
day2_eve_h, day2_eve_m = gauss_jitter(21)

day2_zinger = (
    "UA spoofing alone in 2026 is like locking your car with a Post-it note. "
    "if you arent matching your Client Hints and navigator properties to that UA string, "
    "you're handing the bot-catcher a neon sign that says \"I AM A BOT\". still living in 2015?"
)

day2_mid_supp = (
    "anti-bot pop quiz: how many entropy bits does navigator.webdriver leak? "
    "answer: 1, but combined with mismatched Client Hints + missing chrome.runtime, you light up like a christmas tree"
)

day2_eve_post = (
    "evening note: most anti-bot vendors fingerprint via 30+ signals, not 3. "
    "patching navigator.webdriver and calling it a day is 2018 thinking. "
    "you need to patch the full surface or just accept you'll get caught"
)

day2_queue = {
    'date': day2_date.isoformat(),
    'day_n': 2,
    'track': 'T2 Anti-Bot Wars',
    'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    'generated_by': 'cowork',
    'posts': [
        post(day2_mid_supp, iso(day2_date, day2_mid_h, day2_mid_m),
             tags=['educational', 'mid-day']),
        post(day2_zinger, iso(day2_date, day2_hook_h, day2_hook_m),
             tags=['hook', 'zinger', 'hot-take']),
        post(day2_eve_post, iso(day2_date, day2_eve_h, day2_eve_m),
             tags=['evening', 'educational']),
    ]
}

# ─── Day 3 (2026-05-21) — Perşembe ─────────────────────────────────────────
# day-003.md → T3 AI Agents: LLM-to-CDP bridge (3-tweet medium)
day3_date = LAUNCH + timedelta(days=2)
day3_mid_h, day3_mid_m = gauss_jitter(14)
day3_hook_h, day3_hook_m = gauss_jitter(17)
day3_eve_h, day3_eve_m = gauss_jitter(21)

day3_mid_supp = (
    "quick one for the AI agent crowd: DOM snapshots are noise, accessibility tree is signal. "
    "your agent doesnt need to see every <div>, it needs to see what's actually interactive"
)

day3_hook = (
    "Connecting an LLM to a browser is the \"hello world\" of agents right now. "
    "Most people just dump the whole DOM into context. Lazy, expensive, and 90% noise. "
    "Why are we still burning tokens on nested divs with no content?"
)

day3_evening_thread = [
    "raw CDP gives you the Accessibility Tree. cleaner, semantic, doesnt waste 30k tokens on empty spans. "
    "cdpilot extracts just the AXT — your agent sees what a screen reader sees. only the interactive stuff",
    "DOM snapshots are noise. use the accessibility tree or targeted CDP queries to keep your agent focused "
    "and your bill manageable",
    "source: https://github.com/nadirabbas/cdpilot"
]

day3_queue = {
    'date': day3_date.isoformat(),
    'day_n': 3,
    'track': 'T3 AI Agents',
    'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    'generated_by': 'cowork',
    'posts': [
        post(day3_mid_supp, iso(day3_date, day3_mid_h, day3_mid_m),
             tags=['educational', 'mid-day']),
        post(day3_hook, iso(day3_date, day3_hook_h, day3_hook_m),
             tags=['hook', 'question-bait']),
        post(None, iso(day3_date, day3_eve_h, day3_eve_m),
             tags=['evening', 'thread', 'educational', 'aiagents'],
             thread=day3_evening_thread),
    ]
}

# ─── Write all 3 files ─────────────────────────────────────────────────────
for q in [day1_queue, day2_queue, day3_queue]:
    fpath = os.path.join(QUEUE_DIR, f"{q['date']}.json")
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(q, f, indent=2, ensure_ascii=False)
    print(f"✓ {fpath} — {len(q['posts'])} posts, track: {q['track']}")
    for p in q['posts']:
        kind = 'thread' if p.get('thread') else 'post'
        preview = (p.get('content') or p.get('thread', [''])[0])[:60].replace('\n', ' ')
        print(f"    {p['scheduled_time']} | {kind:6s} | {preview}…")

# today.json kopyası
import shutil
shutil.copy(os.path.join(QUEUE_DIR, f"{day1_date.isoformat()}.json"),
            os.path.join(QUEUE_DIR, 'today.json'))
print(f"\n✓ today.json copy created")

# Heartbeat update
with open(os.path.join(DATA_DIR, 'heartbeat.txt'), 'w') as f:
    f.write(datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))

# State.json update
state_path = os.path.join(DATA_DIR, 'state.json')
state = json.load(open(state_path)) if os.path.exists(state_path) else {}
state['last_cowork_run'] = datetime.now().astimezone().isoformat(timespec='seconds')
state['last_grok_mention'] = state.get('last_grok_mention')  # preserve
state['last_comeback_index'] = state.get('last_comeback_index')
with open(state_path, 'w') as f:
    json.dump(state, f, indent=2)

print(f"\n✓ heartbeat + state updated")
print(f"\n✓ Day 1 launch — Track: T1 Foundations (CDP WebSocket session init)")
