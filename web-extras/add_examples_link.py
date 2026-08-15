"""Add the floating "Quickstart Examples" button to the built frontend index.html.

Usage: python3 add_examples_link.py <path-to-index.html>
(Invoked from the Dockerfile after the Vue build is copied in.)
"""
import sys
from pathlib import Path

LINK = (
    '<a href="/examples.html" style="position:fixed;right:18px;bottom:18px;z-index:9999;'
    "background:#1677ff;color:#fff;padding:10px 16px;border-radius:24px;"
    'font:600 14px/1 system-ui,sans-serif;text-decoration:none;'
    'box-shadow:0 4px 14px rgba(22,119,255,.4)">Quickstart Examples</a>'
)


def main() -> None:
    path = Path(sys.argv[1])
    html = path.read_text()
    assert "</body>" in html, f"anchor not found in {path}"
    path.write_text(html.replace("</body>", LINK + "</body>"))
    print(f"added examples link to {path}")


if __name__ == "__main__":
    main()
