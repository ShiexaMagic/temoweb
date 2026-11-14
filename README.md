# temoweb

Portfolio site for Temo Rekhviashvili, with a web editor so he can change
everything on the page himself.

## How it works

Everything runs on Vercel, on the free plan.

| Part | What it is |
| --- | --- |
| Public site | Static `index.html` + `styles.css` + `script.js` + `Images/` |
| Editor | Flask app (`app.py`) at `/admin`, run as a serverless function (`api/index.py`) |
| Content | `content.json` — every text, link, image name, section order |

Vercel keeps no files between requests, so the GitHub repository is the
storage. The editor reads `content.json` and the image list from GitHub.
Pressing **Save & publish** rebuilds `index.html` from `templates/index.html`
and commits it, `content.json` and any newly uploaded images in a single
commit. Vercel then redeploys the public site (about a minute).

## What can be edited at `/admin`

- Name, tagline, intro and photo on the first screen
- Books, plays and films: add, delete, reorder, hide; cover, texts, details
  table, buttons/links. Each one gets its own page at `/#/<id>`
- Acting credits, press list, biography, highlights, fields, CV file, contact
  details and extra links
- Every section heading, label and footnote; which sections are shown, their
  order and their names in the menu
- Footer, Google title/description, share image
- Image library (large photos are resized in the browser before upload; PDFs
  up to 4 MB are allowed)

In text boxes, `*stars*` make italics and `[text](https://…)` makes a link.

## Environment variables

Set these in the Vercel project under **Settings → Environment Variables**,
then redeploy.

| Variable | Purpose |
| --- | --- |
| `ADMIN_USERNAME` | Editor login name (default `admin`) |
| `ADMIN_PASSWORD_HASH` | Password hash — see below. Required |
| `GITHUB_TOKEN` | Fine-grained token for this repo with **Contents: Read and write**. Required: it is how the editor reads and saves |
| `SECRET_KEY` | Any long random string, used to sign the login cookie. Recommended |
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
`GITHUB_TOKEN` the editor works on the files in this folder and pushes
nothing; `python build.py` regenerates `index.html` by hand.
