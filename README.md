# temoweb

Portfolio site for Temo Rekhviashvili, with a web editor so he can change
everything on the page himself.

## How it works

| Part | What it is | Where it runs |
| --- | --- | --- |
| Public site | Static `index.html` + `styles.css` + `script.js` + `Images/` | Vercel |
| Editor | Flask app (`app.py`), at `/admin` | Railway |
| Content | `content.json` — every text, link, image name, section order | this repo |

Pressing **Save & publish** in the editor writes `content.json`, rebuilds
`index.html` from `templates/index.html`, and commits both — together with any
uploaded or deleted images — to GitHub in a single commit. Vercel then
redeploys the public site (about a minute).

## What can be edited at `/admin`

- Name, tagline, intro and photo on the first screen
- Books, plays and films: add, delete, reorder, hide; cover, texts, details
  table, buttons/links. Each one gets its own page at `/#/<id>`
- Acting credits, press list, biography, highlights, fields, CV file, contact
  details and extra links
- Every section heading, label and footnote; which sections are shown, their
  order and their names in the menu
- Footer, Google title/description, share image
- Image library (large photos are resized on upload; PDFs are allowed)

In text boxes, `*stars*` make italics and `[text](https://…)` makes a link.

## Environment variables (Railway)

| Variable | Purpose |
| --- | --- |
| `ADMIN_USERNAME` | Editor login name (default `admin`) |
| `ADMIN_PASSWORD_HASH` | Password hash — see below. Setting it turns on hosted mode |
| `SECRET_KEY` | Any long random string; keeps you signed in across restarts |
| `GITHUB_TOKEN` | Token with **Contents: read and write** on this repo. Without it, saves stay on the server and are not published |
| `GITHUB_REPO` | `owner/name` (default `ShiexaMagic/temoweb`) |
| `GITHUB_BRANCH` | Branch Vercel deploys from (default `main`) |

Create a password hash:

```bash
python -c "from werkzeug.security import generate_password_hash as g; print(g(input('Password: ')))"
```

## Run locally

```bash
pip install -r requirements.txt
```

```bash
python app.py
```

Open http://localhost:5000/admin. The first run creates `admin_config.json`
with the login `admin` / `admin` — change it under **Account**. Without
`GITHUB_TOKEN` nothing is pushed; run `python build.py` to regenerate
`index.html` by hand.
