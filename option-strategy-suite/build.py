#!/usr/bin/env python3
"""Bundle the suite into one self-contained HTML file.

    python3 build.py            -> dist/nifty-option-suite.html
    python3 build.py --zip      -> that, plus dist/niftyoptionsuite.zip

The single file has the stylesheet and every script inlined, so it runs by
double-clicking it — no server, no network, no dependencies. Useful for
carrying the tool on a laptop or phone; for day-to-day work prefer ./serve.sh,
because browsers restrict localStorage on file:// and your saved settings and
language will not persist there.

--zip packages the whole project for handing to a Windows machine. It collects
by pattern rather than from a hand-kept list, which had already gone stale
twice — a new script or icon is picked up automatically.
"""

import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "dist" / "nifty-option-suite.html"
ZIP = ROOT / "dist" / "niftyoptionsuite.zip"

# Everything a Windows user needs, by pattern. Ordered for a readable listing.
ZIP_GLOBS = [
    "index.html", "manifest.webmanifest",
    "README.md", "WINDOWS.md", "IOS.md",
    "*.cmd", "serve.sh", "build.py",
    "assets/css/*.css", "assets/icons/*", "assets/js/*.js",
    "tools/*.js",
    "dist/nifty-option-suite.html",
]

LINK = re.compile(r'[ \t]*<link rel="stylesheet" href="([^"]+)"\s*/?>\s*\n')
SCRIPT = re.compile(r'[ \t]*<script src="([^"]+)"></script>\s*\n')

# The home-screen icon and manifest are separate files by necessity — iOS
# ignores a data: URI for apple-touch-icon. They cannot resolve from a lone
# HTML file, and this bundle promises no external requests, so drop them.
# Installing to a phone's home screen is the served path's job, not this one.
EXTERNAL = re.compile(
    r'[ \t]*<link rel="(?:apple-touch-icon|manifest)"[^>]*>\s*\n'
)


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


def make_zip():
    """Package the project. Call only after the bundle has been written."""
    seen = []
    for pattern in ZIP_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.append(path)

    if not seen:
        raise SystemExit("nothing matched the zip patterns — wrong directory?")

    # netlify.toml lives one level up, beside the repo's other deploy config.
    extra = (ROOT.parent / "netlify.toml")

    ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for path in seen:
            z.write(path, path.relative_to(ROOT).as_posix())
        if extra.is_file():
            z.write(extra, "netlify.toml")

    count = len(seen) + (1 if extra.is_file() else 0)
    print(f"\n  {ZIP.relative_to(ROOT)}  ({ZIP.stat().st_size / 1024:.0f} KB, {count} files)")
    print("  extract it on the Windows machine and double-click start.cmd.")


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
    html, dropped = EXTERNAL.subn("", html)

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
    if dropped:
        print(f"  dropped  {dropped} link(s) that cannot resolve from a single file")
    print(f"\n  {OUT.relative_to(ROOT)}  ({size / 1024:.0f} KB, {css_count} stylesheet, {js_count} scripts)")
    print("  open it directly in a browser — nothing else needed.")

    if "--zip" in sys.argv[1:]:
        make_zip()
    return 0


if __name__ == "__main__":
    sys.exit(main())
