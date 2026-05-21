#!/usr/bin/env python3
"""
twikit ile hemen tek tweet at — cdpilot/Chrome bypass.
Mac cookies (/tmp/x-cookies.json) kullanılır.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from twikit import Client

COOKIES_PATH = "/tmp/x-cookies.json"
QUEUE_FILE = os.path.expanduser("~/cdpilot-twitter-data/queue/2026-05-19.json")


async def main():
    # cdpilot cookies output → twikit dict format
    with open(COOKIES_PATH) as f:
        cookies_list = json.load(f)
    cookies_dict = {c["name"]: c["value"] for c in cookies_list}

    print(f"Loaded {len(cookies_dict)} cookies", file=sys.stderr)
    print(f"  keys: {list(cookies_dict.keys())}", file=sys.stderr)

    if "auth_token" not in cookies_dict or "ct0" not in cookies_dict:
        print("FAIL: missing auth_token or ct0", file=sys.stderr)
        sys.exit(1)

    client = Client("en-US")
    client.set_cookies(cookies_dict)

    # Test auth — kendi profilimizi çek
    me = await client.user()
    print(f"Logged in as: @{me.screen_name} (name={me.name})", file=sys.stderr)

    # Queue'dan pending mid-day Tweet 2'yi al
    with open(QUEUE_FILE) as f:
        q = json.load(f)
    target = None
    for p in q["posts"]:
        if p["status"] == "pending" and p["type"] == "post":
            target = p
            break
    if not target:
        print("FAIL: no pending post in queue", file=sys.stderr)
        sys.exit(1)

    content = target["content"]
    print(f"\nPosting: {content[:100]}…\n", file=sys.stderr)

    tweet = await client.create_tweet(text=content)
    tweet_id = tweet.id
    tweet_url = f"https://x.com/{me.screen_name}/status/{tweet_id}"

    # Queue update
    target["status"] = "done"
    target["result_url"] = tweet_url
    target["error"] = None
    with open(QUEUE_FILE, "w") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)

    print(json.dumps({"tweet_id": tweet_id, "url": tweet_url}, indent=2))


asyncio.run(main())
