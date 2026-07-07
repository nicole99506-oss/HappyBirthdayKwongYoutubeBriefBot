"""Build the reading site (GitHub Pages) from stored summaries.

Design: a private wire service. Cool celadon paper, spruce ink, deep-teal accent.
Signature element: every briefing carries a monospace "wire slug" showing the
compression the system performs — WATCH 18 MIN -> READ 2 MIN.
"""
import html
import json
import os
import shutil

from . import config

CSS = """
:root{
  --paper:#EDF0EC; --card:#F6F8F4; --ink:#17251F; --muted:#5C6B62;
  --accent:#0E6B5A; --signal:#B85C00; --hair:#C9D2CA;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:'Newsreader',Georgia,serif;font-size:17px;line-height:1.55}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 80px}
header.masthead{border-bottom:3px double var(--ink);padding:44px 0 18px;margin-bottom:8px}
.masthead h1{font-family:'Young Serif',Georgia,serif;font-size:clamp(30px,6vw,52px);
  margin:0;letter-spacing:-.01em;line-height:1.05}
.masthead h1 span{color:var(--accent)}
.masthead .sub{font-family:'Spline Sans Mono',monospace;font-size:12px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-top:10px}
.chips{display:flex;flex-wrap:wrap;gap:8px;padding:16px 0;border-bottom:1px solid var(--hair)}
.chip{font-family:'Spline Sans Mono',monospace;font-size:12px;letter-spacing:.06em;
  border:1px solid var(--ink);border-radius:999px;padding:5px 13px;color:var(--ink)}
.chip:hover{background:var(--ink);color:var(--paper);text-decoration:none}
.daterule{font-family:'Spline Sans Mono',monospace;font-size:12px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--muted);margin:34px 0 6px;display:flex;
  align-items:center;gap:12px}
.daterule::after{content:"";flex:1;border-top:1px solid var(--hair)}
article.brief{background:var(--card);border:1px solid var(--hair);border-left:4px solid var(--accent);
  padding:18px 22px;margin:14px 0;border-radius:2px}
.slug{font-family:'Spline Sans Mono',monospace;font-size:11px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted)}
.slug b{color:var(--signal);font-weight:600}
article.brief h2{font-family:'Young Serif',Georgia,serif;font-size:23px;margin:8px 0 6px;line-height:1.22}
article.brief h2 a{color:var(--ink)}
.tldr{margin:6px 0 4px}
.tldr strong{color:var(--accent);font-family:'Spline Sans Mono',monospace;
  font-size:11px;letter-spacing:.12em}
details{margin-top:8px}
summary{cursor:pointer;font-family:'Spline Sans Mono',monospace;font-size:12px;
  letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
summary:hover{color:var(--ink)}
.body h3{font-family:'Spline Sans Mono',monospace;font-size:12px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted);margin:20px 0 6px}
.body ul{margin:6px 0;padding-left:20px}
.body li{margin:5px 0}
.why{border-top:1px solid var(--hair);margin-top:16px;padding-top:10px;font-style:italic}
.mindmap{width:100%;border:1px solid var(--hair);border-radius:2px;margin:14px 0;background:#fff}
footer{margin-top:60px;border-top:3px double var(--ink);padding-top:14px;
  font-family:'Spline Sans Mono',monospace;font-size:11px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted)}
@media (prefers-reduced-motion: no-preference){
  article.brief{transition:transform .15s ease}
  article.brief:hover{transform:translateX(2px)}
}
"""

HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Young+Serif&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Spline+Sans+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">
<header class="masthead"><h1>Happy Birthday <span>Kwong</span></h1>
<div class="sub">The global political economy wire · summarized, mapped, delivered · with love from Nicole</div></header>
"""

FOOT = """<footer>Generated automatically · GitHub Actions · Gemini · Telegram · Drive</footer>
</div></body></html>"""


def _e(s: str) -> str:
    return html.escape(str(s or ""))


def _brief_html(entry: dict, channel_title: str, link_channel: bool = True) -> str:
    s = entry["data"]
    date = entry["published"][:10]
    ch_html = (f'<a href="channel-{entry["channel_id"]}.html">{_e(channel_title)}</a>'
               if link_channel else _e(channel_title))
    hl = "".join(f"<li>{_e(h)}</li>" for h in s.get("highlights", []))
    kc = "".join(f"<li><strong>{_e(k.get('term',''))}</strong> — {_e(k.get('explanation',''))}</li>"
                 for k in s.get("key_concepts", []))
    paras = "".join(f"<p>{_e(p)}</p>" for p in str(s.get("summary", "")).split("\n") if p.strip())
    return f"""<article class="brief">
<div class="slug">{ch_html} · {date} · <b>watch → 2 min read</b></div>
<h2><a href="{_e(entry['url'])}" target="_blank" rel="noopener">{_e(entry['title'])}</a></h2>
<p class="tldr"><strong>The Gist</strong> — {_e(s.get('tldr',''))}</p>
<details><summary>Read the briefing</summary><div class="body">
<h3>Summary</h3>{paras}
<h3>Highlights</h3><ul>{hl}</ul>
<h3>Key concepts</h3><ul>{kc}</ul>
<p class="why">Why it matters — {_e(s.get('why_it_matters',''))}</p>
</div></details></article>"""


def _load_entries(st: dict) -> list[dict]:
    entries = []
    for cid in st["channels"]:
        cdir = os.path.join(config.SUMMARY_DIR, cid)
        if not os.path.isdir(cdir):
            continue
        for fn in os.listdir(cdir):
            if fn.endswith(".json"):
                with open(os.path.join(cdir, fn), "r", encoding="utf-8") as f:
                    e = json.load(f)
                e["channel_id"] = cid
                entries.append(e)
    entries.sort(key=lambda e: e["published"], reverse=True)
    return entries


def build(st: dict) -> None:
    os.makedirs(config.DOCS_DIR, exist_ok=True)
    entries = _load_entries(st)
    titles = {cid: ch["title"] for cid, ch in st["channels"].items()}

    # copy mind map PNGs into docs/ for embedding
    mm_dir = os.path.join(config.DOCS_DIR, "mindmaps")
    os.makedirs(mm_dir, exist_ok=True)
    for cid in st["channels"]:
        src = os.path.join(config.MINDMAP_DIR, f"{cid}.png")
        if os.path.exists(src):
            shutil.copy(src, os.path.join(mm_dir, f"{cid}.png"))

    # ---- index ----
    parts = [HEAD.format(title="Happy Birthday Kwong", css=CSS)]
    if titles:
        parts.append('<nav class="chips">')
        for cid, t in sorted(titles.items(), key=lambda kv: kv[1].lower()):
            parts.append(f'<a class="chip" href="channel-{cid}.html">{_e(t)}</a>')
        parts.append("</nav>")
    last_date = None
    for e in entries[:40]:
        d = e["published"][:10]
        if d != last_date:
            parts.append(f'<div class="daterule">{d}</div>')
            last_date = d
        parts.append(_brief_html(e, titles.get(e["channel_id"], "")))
    if not entries:
        parts.append("<p style='margin-top:40px'>No briefings yet. Add a channel in "
                     "Telegram with <code>/add @handle</code> and this page fills itself.</p>")
    parts.append(FOOT)
    with open(os.path.join(config.DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write("".join(parts))

    # ---- per-channel pages ----
    for cid, title in titles.items():
        ch_entries = [e for e in entries if e["channel_id"] == cid]
        parts = [HEAD.format(title=f"{title} — Happy Birthday Kwong", css=CSS)]
        parts.append(f'<nav class="chips"><a class="chip" href="index.html">← All briefings</a></nav>')
        parts.append(f'<div class="daterule">{_e(title)} · knowledge map</div>')
        if os.path.exists(os.path.join(mm_dir, f"{cid}.png")):
            parts.append(f'<img class="mindmap" src="mindmaps/{cid}.png" alt="Mind map of {_e(title)}">')
        for e in ch_entries:
            parts.append(_brief_html(e, title, link_channel=False))
        parts.append(FOOT)
        with open(os.path.join(config.DOCS_DIR, f"channel-{cid}.html"), "w", encoding="utf-8") as f:
            f.write("".join(parts))
