#!/usr/bin/env python3
"""Copy each example's output/transcript.txt into the "## Captured Output" block of its README.

The README shows the same bytes the last real run produced; nothing is typed by hand.
test/test.js fails when the two drift apart.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
BLOCK = re.compile(r"(## Captured Output\n\n```text\n)(.*?)(```)", re.S)


def main() -> int:
    changed = 0
    for readme in sorted(ROOT.glob("*/README.md")):
        transcript = readme.parent / "output" / "transcript.txt"
        if not transcript.exists():
            continue
        body = transcript.read_text(encoding="utf-8")
        if not body.endswith("\n"):
            body += "\n"
        text = readme.read_text(encoding="utf-8")
        if not BLOCK.search(text):
            print(f"{readme.parent.name}: no '## Captured Output' block", file=sys.stderr)
            return 1
        new = BLOCK.sub(lambda m: m.group(1) + body + m.group(3), text, count=1)
        if new != text:
            readme.write_text(new, encoding="utf-8")
            changed += 1
            print(f"synced {readme.parent.name}")
    print(f"{changed} README(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
