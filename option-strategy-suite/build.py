#!/usr/bin/env python3
"""Bundle the suite into one self-contained HTML file.

    python3 build.py            -> dist/nifty-option-suite.html

The output has the stylesheet and every script inlined, so it runs by
double-clicking it — no server, no network, no dependencies. Useful for
carrying the tool on a laptop or phone; for day-to-day work prefer ./serve.sh,
because browsers restrict localStorage on file:// and your saved settings and
language will not persist there.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "dist" / "nifty-option-suite.html"

LINK = re.compile(r'[ \t]*<link rel="stylesheet" href="([^"]+)"\s*/?>\s*\n')
SCRIPT = re.compile(r'[ \t]*<script src="([^"]+)"></script>\s*\n')


def read(rel):
    path = (ROOT / rel).resolve()
    if ROOT not in path.parents:
        raise SystemExit(f"refusing to inline outside the project: {rel}")
    if not path.is_file():
        raise SystemExit(f"missing asset: {rel}")
    return path.read_text(encoding="utf-8")


def guard(text, rel):
    """A literal </script> inside JS would close the tag early."""
    if "</script" in text.lower():
        raise SystemExit(f"{rel} contains a literal </script> and cannot be inlined as-is")
    return text


def main():
    html = read("index.html")
    inlined = []

    def css(match):
        rel = match.group(1)
        inlined.append(rel)
        return "<style>\n" + read(rel).rstrip() + "\n</style>\n"

    def js(match):
        rel = match.group(1)
        inlined.append(rel)
        return "<script>\n" + guard(read(rel), rel).rstrip() + "\n</script>\n"

    html, css_count = LINK.subn(css, html)
    html, js_count = SCRIPT.subn(js, html)

    if css_count == 0 or js_count == 0:
        raise SystemExit("found no assets to inline — has index.html changed shape?")

    html = html.replace(
        "<head>",
        "<head>\n<!-- Built by build.py: single-file bundle, no external requests. -->",
        1,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    for rel in inlined:
        print(f"  inlined  {rel}")
    size = OUT.stat().st_size
    print(f"\n  {OUT.relative_to(ROOT)}  ({size / 1024:.0f} KB, {css_count} stylesheet, {js_count} scripts)")
    print("  open it directly in a browser — nothing else needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
