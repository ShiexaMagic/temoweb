"""
Content model shared by the admin app (app.py) and the static builder
(build.py).

content.json is the single source of truth for everything shown on the
public page.  `normalize()` turns whatever is stored (including content
saved by older versions of the admin) into the current shape, so the
template never has to guess whether a key exists.
"""
import copy
import hashlib
import json
import os
import re
import time

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

BASE = os.path.dirname(os.path.abspath(__file__))
CONTENT_FILE = os.path.join(BASE, "content.json")
IMAGES_DIR = os.path.join(BASE, "Images")
OUTPUT_FILE = os.path.join(BASE, "index.html")

SECTION_KEYS = ["books", "theatre", "cinema", "press", "about", "contact"]

DEFAULTS = {
    "site": {
        "name": "Temo Rekhviashvili",
        "seo_title": "Temo Rekhviashvili | Writer, Playwright, Actor",
        "seo_description": "Portfolio website for Temo Rekhviashvili, Georgian writer, playwright, and actor.",
        "url": "",
        "share_image": "",
        "footer_text": "Writer · Playwright · Actor",
    },
    "hero": {"tagline": "", "bio": "", "image": ""},
    "section_order": SECTION_KEYS,
    "sections": {
        "books": {
            "visible": True,
            "nav": "Books",
            "heading": "Books",
            "note": "Three books in Georgian. Translation rights are held by the author. English samples and synopses are available.",
        },
        "theatre": {
            "visible": True,
            "nav": "Theatre",
            "heading": "Theatre",
            "note": "Stage work as playwright and actor.",
            "plays_label": "Playwright / Dramatic Writing",
            "credits_label": "Actor",
            "credits_heading": "Selected stage acting credits",
            "credits_note": "A concise selection of theatre roles.",
            "credits_footnote": "Full theatre CV available on request.",
        },
        "cinema": {
            "visible": True,
            "nav": "Cinema",
            "heading": "Cinema",
            "note": "Film work as writer, co-screenwriter and actor.",
            "films_label": "Films",
            "credits_label": "Selected screen acting credits",
            "credits_footnote": "Full filmography available on IMDb.",
            "credits_link_label": "IMDb",
            "credits_link_url": "",
        },
        "press": {"visible": True, "nav": "Press", "heading": "Press", "note": ""},
        "about": {
            "visible": True,
            "nav": "About",
            "heading": "About",
            "highlights_label": "Selected highlights",
            "fields_label": "Fields",
            "cv_label": "Download CV",
        },
        "contact": {"visible": True, "nav": "Contact", "heading": "Get in touch"},
    },
    "rights_note": {
        "visible": True,
        "title": "Rights & Samples",
        "text": "",
        "inquiry_text": "For publishing, translation and adaptation inquiries please get in touch.",
    },
    "about": {
        "image": "",
        "intro": "",
        "paragraphs": [],
        "closing": "",
        "timeline": [],
        "fields": [],
    },
    "cv": {"download_url": ""},
    "contact": {"description": "", "email": "", "links": []},
}

# Collections of "works": each item opens a detail page.
WORK_LISTS = ["books", "theatre_plays", "films"]
# Simple row tables: list key -> column names.
ROW_LISTS = {
    "theatre_credits": ["title", "venue", "detail"],
    "cinema_credits": ["title", "venue", "year"],
    "press": ["year", "text", "url"],
}


# ── Small coercion helpers ──────────────────────────────────────
def _s(value):
    """Any value -> trimmed string."""
    if value is None:
        return ""
    return str(value).strip()


def _paragraphs(value):
    """Accept a string or list of strings; return clean paragraphs."""
    if isinstance(value, str):
        value = [value]
    out = []
    for chunk in value or []:
        for part in re.split(r"\n\s*\n|\n", _s(chunk)):
            part = part.strip()
            if part:
                out.append(part)
    return out


_SAFE_URL = re.compile(r"^(https?://|mailto:|tel:|/|#)", re.I)


def _url(value):
    """Keep safe URLs as-is; make bare domains clickable; drop the rest."""
    url = _s(value)
    if not url or _SAFE_URL.match(url):
        return url
    if re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", url):
        return "mailto:" + url
    if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):  # javascript:, data:, …
        return ""
    return "https://" + url


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", _s(text).lower()).strip("-")
    return slug[:60]


def _links(value):
    out = []
    for link in value or []:
        if not isinstance(link, dict):
            continue
        label, url = _s(link.get("label")), _url(link.get("url"))
        if label or url:
            out.append({"label": label or url, "url": url})
    return out


def _details(value):
    out = []
    for row in value or []:
        if not isinstance(row, dict):
            continue
        key, val = _s(row.get("key")), _s(row.get("value"))
        if key or val:
            out.append({"key": key, "value": val})
    return out


def _work(item, used_ids):
    """Normalise a book / play / film."""
    item = item if isinstance(item, dict) else {}
    title = _s(item.get("title"))
    # Older content used `description` (plays) instead of `paragraphs`.
    paragraphs = _paragraphs(item.get("paragraphs")) or _paragraphs(item.get("description"))
    # Older content used `year` (plays, films) as the meta line.
    meta = _s(item.get("meta_line1")) or _s(item.get("year"))

    base = _slug(item.get("id")) or _slug(title) or "item"
    wid, n = base, 2
    while wid in used_ids:
        wid, n = f"{base}-{n}", n + 1
    used_ids.add(wid)

    return {
        "id": wid,
        "visible": item.get("visible", True) is not False,
        "label": _s(item.get("label")),
        "title": title,
        "image": _s(item.get("image")),
        "meta_line1": meta,
        "meta_line2": _s(item.get("meta_line2")),
        "summary": _s(item.get("summary")),
        "paragraphs": paragraphs,
        "details": _details(item.get("details")),
        "links": _links(item.get("links")),
    }


def _merge(defaults, value):
    """Shallow, type-safe merge of a stored dict over a dict of defaults."""
    out = copy.deepcopy(defaults)
    if not isinstance(value, dict):
        return out
    for key, default in defaults.items():
        if key not in value:
            continue
        if isinstance(default, bool):
            out[key] = bool(value[key])
        elif isinstance(default, str):
            out[key] = _s(value[key])
        else:
            out[key] = value[key]
    return out


def normalize(raw):
    """Return content in the current schema.  Never raises on odd input."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}

    out["site"] = _merge(DEFAULTS["site"], raw.get("site"))
    out["site"]["url"] = _url(out["site"]["url"]).rstrip("/")
    out["hero"] = _merge(DEFAULTS["hero"], raw.get("hero"))

    stored_sections = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
    out["sections"] = {
        key: _merge(DEFAULTS["sections"][key], stored_sections.get(key)) for key in SECTION_KEYS
    }
    out["sections"]["cinema"]["credits_link_url"] = _url(out["sections"]["cinema"]["credits_link_url"])

    order = [k for k in (raw.get("section_order") or []) if k in SECTION_KEYS]
    out["section_order"] = list(dict.fromkeys(order + SECTION_KEYS))

    # Works.  `cinema_featured` (a single film) is the pre-redesign shape.
    films = raw.get("films")
    if films is None and isinstance(raw.get("cinema_featured"), dict):
        films = [raw["cinema_featured"]]
    lists = {"books": raw.get("books"), "theatre_plays": raw.get("theatre_plays"), "films": films}
    used_ids = set(SECTION_KEYS) | {"home"}
    for key in WORK_LISTS:
        out[key] = [_work(item, used_ids) for item in (lists[key] or [])]

    for key, columns in ROW_LISTS.items():
        rows = []
        for row in raw.get(key) or []:
            if not isinstance(row, dict):
                continue
            clean = {c: (_url(row.get(c)) if c == "url" else _s(row.get(c))) for c in columns}
            if any(clean.values()):
                rows.append(clean)
        out[key] = rows

    out["rights_note"] = _merge(DEFAULTS["rights_note"], raw.get("rights_note"))

    about = _merge(DEFAULTS["about"], raw.get("about"))
    about["paragraphs"] = _paragraphs(about["paragraphs"])
    about["timeline"] = [
        {"year": _s(t.get("year")), "text": _s(t.get("text"))}
        for t in (about["timeline"] or [])
        if isinstance(t, dict) and (_s(t.get("year")) or _s(t.get("text")))
    ]
    fields = about["fields"]
    if isinstance(fields, str):
        fields = fields.split("\n")
    about["fields"] = [_s(f) for f in (fields or []) if _s(f)]
    out["about"] = about

    out["cv"] = _merge(DEFAULTS["cv"], raw.get("cv"))
    out["cv"]["download_url"] = _url(out["cv"]["download_url"])

    contact = _merge(DEFAULTS["contact"], raw.get("contact"))
    contact["links"] = _links(contact["links"])
    out["contact"] = contact
    return out


# ── Storage ─────────────────────────────────────────────────────
def load_content():
    with open(CONTENT_FILE, "r", encoding="utf-8") as f:
        return normalize(json.load(f))


def save_content(data):
    data = normalize(data)
    tmp = CONTENT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CONTENT_FILE)
    return data


def image_exists(name):
    return bool(name) and os.path.isfile(os.path.join(IMAGES_DIR, name))


def referenced_images(content):
    """Every image filename the content points at."""
    names = {content["hero"]["image"], content["about"]["image"], content["site"]["share_image"]}
    for key in WORK_LISTS:
        names.update(item["image"] for item in content[key])
    names.discard("")
    return names


# ── Rendering ───────────────────────────────────────────────────
_LINK = re.compile(r"\[([^\]\n]+)\]\(((?:https?://|mailto:|/)[^\s)]+)\)")
_EM = re.compile(r"\*([^*\n]+)\*")


def rich(text):
    """Escape text, then allow *italics* and [links](https://…)."""
    html = str(escape(_s(text)))
    html = _LINK.sub(r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', html)
    html = _EM.sub(r"<em>\1</em>", html)
    return Markup(html)


def view_model(content):
    """Content prepared for the template: hidden things removed, missing
    images blanked so the page shows a placeholder instead of a broken image."""
    c = copy.deepcopy(content)

    def img(name):
        return name if image_exists(name) else ""

    c["hero"]["image"] = img(c["hero"]["image"]) or img("Temo Image.jpeg")
    c["about"]["image"] = img(c["about"]["image"])
    c["site"]["share_image"] = img(c["site"]["share_image"]) or c["hero"]["image"]
    for key in WORK_LISTS:
        items = [w for w in c[key] if w["visible"] and w["title"]]
        for w in items:
            w["image"] = img(w["image"])
        c[key] = items
    c["visible_sections"] = [k for k in c["section_order"] if c["sections"][k]["visible"]]
    return c


def _env():
    env = Environment(
        loader=FileSystemLoader(os.path.join(BASE, "templates")),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["rich"] = rich
    return env


def _asset_version():
    """Cache-busting stamp for styles.css / script.js."""
    digest = hashlib.md5()
    for name in ("styles.css", "script.js"):
        with open(os.path.join(BASE, name), "rb") as f:
            digest.update(f.read())
    return digest.hexdigest()[:8]


def render_site(content=None):
    content = load_content() if content is None else normalize(content)
    template = _env().get_template("index.html")
    return template.render(
        content=view_model(content),
        year=time.gmtime().tm_year,
        v=_asset_version(),
    )


def build():
    html = render_site()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    return OUTPUT_FILE
