"""
Static site builder.

Renders templates/index.html with content.json and writes the result to
index.html in the project root.  Vercel serves that file as a plain static
site — no Python runtime needed in production.

Usage:
    python build.py
"""
from site_content import build

if __name__ == "__main__":
    build()
    print("Built: index.html")
