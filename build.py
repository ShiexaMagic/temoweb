"""
Static site builder.

Renders templates/index.html with content.json and writes the result to
index.html in the project root.  Vercel serves that file as a plain static
site — no Python runtime needed in production.

Usage:
    python build.py
"""
import json
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE = os.path.dirname(os.path.abspath(__file__))


def build() -> None:
    with open(os.path.join(BASE, "content.json"), "r", encoding="utf-8") as f:
        content = json.load(f)

    env = Environment(
        loader=FileSystemLoader(os.path.join(BASE, "templates")),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("index.html")
    html = template.render(content=content)

    out = os.path.join(BASE, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    build()
    print("Built: index.html")
