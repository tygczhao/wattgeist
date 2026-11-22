"""Render the WattGeist ghost icon as the opaque 512x512 PNG the Kiro Crew app store expects (headless Chrome screenshot).

Usage: uv run --project backend --with playwright python scripts/make_icon.py <output png>
"""

import sys

from playwright.sync_api import sync_playwright

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="512" height="512">
<rect width="64" height="64" rx="14" fill="#16141d"/>
<circle cx="47" cy="15" r="7" fill="#efe9de" opacity="0.18"/>
<path d="M32 9c-11 0-18 8-18 19v24l5.4-4.5 4.5 4.5 4.5-4.5 3.6 4.5 3.6-4.5 4.5 4.5 4.5-4.5 5.4 4.5V28C50 17 43 9 32 9z" fill="#efe9de"/>
<circle cx="25" cy="28" r="3.6" fill="#16141d"/><circle cx="39" cy="28" r="3.6" fill="#16141d"/>
<path d="M33.5 33l-5.5 8.5h4.6l-2.8 7.5 8.4-10.2h-4.6l2.8-5.8z" fill="#d95926"/>
</svg>"""

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 512, "height": 512})
    pg.set_content(f"<html><body style='margin:0;background:#16141d'>{SVG}</body></html>")
    pg.screenshot(path=sys.argv[1], omit_background=False)
    b.close()
print("wrote", sys.argv[1])
