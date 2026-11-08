"""Profile README pipeline.

extract   -> read public data from the GitHub REST API
transform -> aggregate stars, release downloads and language bytes
load      -> write themed SVGs (dark + light) into assets/

Runs daily on GitHub Actions (see .github/workflows/pipeline.yml).
Standard library only, so the workflow needs no `pip install`.

Local run (CMD):  python pipeline\\build.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import urllib.request
from html import escape

USER = "Thiscesarr"
ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

MONO = "ui-monospace,SFMono-Regular,'Cascadia Code',Consolas,'Liberation Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"

THEMES = {
    "dark": {
        "bg": "#0d1117", "card": "#161b22", "border": "#30363d", "grid": "#1f2630",
        "text": "#e6edf3", "muted": "#8b949e", "accent": "#22d3ee", "violet": "#a78bfa",
        "amber": "#fbbf24", "green": "#3fb950", "chip": "#1f2937",
    },
    "light": {
        "bg": "#ffffff", "card": "#f6f8fa", "border": "#d0d7de", "grid": "#e6eaef",
        "text": "#1f2328", "muted": "#59636e", "accent": "#0e7490", "violet": "#6d28d9",
        "amber": "#b45309", "green": "#1a7f37", "chip": "#eaeef2",
    },
}

# Linguist colors, so the language bar matches what GitHub shows.
LANG_COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "Java": "#b07219", "TypeScript": "#3178c6",
    "CSS": "#663399", "HTML": "#e34c26", "PowerShell": "#012456", "Inno Setup": "#264b99",
    "Batchfile": "#C1F12E", "Kotlin": "#A97BFF", "Shell": "#89e051", "SQL": "#e38c00",
}

# Curated copy for the featured cards; live numbers come from the API.
FEATURED = {
    "jungle-splits": {
        "badge": "WINDOWS APP",
        "tagline": "F1-style split timer for League of Legends jungle clears. "
                   "Purple, green and red sectors with a live delta to your PB.",
        "stack": ["python", "overlay", "inno setup"],
    },
    "data-engineering-roadmap": {
        "badge": "LIVE SITE",
        "tagline": "Interactive roadmap from zero to Staff: 15 phases, 88 topics, "
                   "~580 questions with spaced-repetition review.",
        "stack": ["javascript", "pwa", "pt / en"],
    },
}


# Private work: the workflow token cannot read private repos, so this card is
# curated by hand. No repo name or link, only what is fine to say in public.
LAB = [
    {
        "name": "android pantry app",
        "badge": "PRIVATE · WIP",
        "tagline": "Android app that tracks food expiry, refills the shopping list "
                   "and suggests recipes for what expires first.",
        "stack": ["kotlin", "compose", "room", "workmanager"],
        "language": "Kotlin",
        "private": True,
    },
]


# Language bytes of private repos, used only when PROFILE_TOKEN is not set.
# Measured from the local clone on 2026-11-08 (tracked files, Linguist-style).
PRIVATE_SNAPSHOT = [{"Kotlin": 449_785, "Python": 9_139, "Batchfile": 1_807}]


# Left out of the language bar: the profile is aimed at data engineering, so
# the Android app's Kotlin would bury Python and SQL work.
EXCLUDED_LANGUAGES = {"Kotlin"}


# --------------------------------------------------------------------------- extract

def api(url: str, token: str | None = None):
    if url.startswith("/"):
        url = "https://api.github.com" + url
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile-pipeline",
    })
    token = token or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def extract() -> list[dict]:
    repos = api(f"/users/{USER}/repos?per_page=100&type=owner")
    repos = [r for r in repos if not r["fork"] and r["name"] != USER]
    for repo in repos:
        repo["_languages"] = api(repo["languages_url"])
        releases = api(f"/repos/{USER}/{repo['name']}/releases?per_page=100")
        repo["_downloads"] = sum(a["download_count"] for r in releases for a in r["assets"])
    return repos


def extract_private() -> list[dict]:
    """Language bytes of private repos. Names never leave this function.

    Needs a fine-grained token (secret PROFILE_TOKEN) with read-only access to
    Metadata on the private repos; without it, falls back to PRIVATE_SNAPSHOT.
    """
    token = os.environ.get("PROFILE_TOKEN")
    if not token:
        return PRIVATE_SNAPSHOT
    repos = api("/user/repos?visibility=private&affiliation=owner&per_page=100", token)
    return [api(r["languages_url"], token) for r in repos if not r["fork"]]


# --------------------------------------------------------------------------- transform

def transform(repos: list[dict], private: list[dict]) -> dict:
    languages: dict[str, int] = {}
    for langs in [r["_languages"] for r in repos] + private:
        for lang, size in langs.items():
            if lang not in EXCLUDED_LANGUAGES:
                languages[lang] = languages.get(lang, 0) + size
    total = sum(languages.values()) or 1
    ranked = sorted(languages.items(), key=lambda kv: kv[1], reverse=True)
    top = [(name, size / total) for name, size in ranked[:6]]
    rest = 1 - sum(share for _, share in top)
    if rest > 0.0005:
        top.append(("Other", rest))

    by_name = {r["name"]: r for r in repos}
    cards = []
    for name, copy in FEATURED.items():
        repo = by_name.get(name)
        if repo:
            cards.append({
                "name": name,
                "language": repo["language"] or "Other",
                "stars": repo["stargazers_count"],
                "downloads": repo["_downloads"],
                "pushed": repo["pushed_at"][:10],
                **copy,
            })

    cards += LAB

    return {
        "repos": len(repos),
        "private": len(private),
        "stars": sum(r["stargazers_count"] for r in repos),
        "downloads": sum(r["_downloads"] for r in repos),
        "language_count": len(languages),
        "languages": top,
        "cards": cards,
        "run_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


# --------------------------------------------------------------------------- load

def svg(width: int, height: int, body: str, style: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f"<style>{style}"
        "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"
        f"</style>{body}</svg>\n"
    )


def header(t: dict) -> str:
    w, h = 1000, 300
    nodes = ["sources", "extract", "transform", "load", "decisions"]
    node_w, gap, y = 150, 47, 222
    x0 = (w - (len(nodes) * node_w + (len(nodes) - 1) * gap)) / 2
    line_y = y + 19
    parts = [
        f'<defs><pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
        f'<circle cx="2" cy="2" r="1.2" fill="{t["grid"]}"/></pattern>'
        f'<linearGradient id="beam" x1="0" x2="1"><stop offset="0" stop-color="{t["accent"]}"/>'
        f'<stop offset="1" stop-color="{t["violet"]}"/></linearGradient></defs>',
        f'<rect width="{w}" height="{h}" rx="16" fill="{t["bg"]}"/>',
        f'<rect width="{w}" height="{h}" rx="16" fill="url(#dots)"/>',
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="16" fill="none" stroke="{t["border"]}"/>',
        # prompt + name
        f'<text x="48" y="62" font-family="{MONO}" font-size="16" fill="{t["muted"]}">'
        f'<tspan fill="{t["green"]}">~/thiscesarr</tspan> <tspan fill="{t["accent"]}">$</tspan> whoami'
        f'<tspan class="cursor" fill="{t["accent"]}"> _</tspan></text>',
        f'<text x="46" y="118" font-family="{SANS}" font-size="46" font-weight="700" '
        f'fill="{t["text"]}" class="rise">Julio Cesar Santos</text>',
        f'<text x="48" y="152" font-family="{SANS}" font-size="19" fill="{t["text"]}" class="rise d1">'
        f'Data Engineering &amp; Analytics <tspan fill="{t["muted"]}">@</tspan> '
        f'<tspan fill="url(#beam)" font-weight="600">Itaú Unibanco</tspan></text>',
        f'<text x="48" y="180" font-family="{MONO}" font-size="13.5" fill="{t["muted"]}" class="rise d2">'
        f'Data Science · São Paulo, BR</text>',
    ]
    # key/value block on the right
    kv = [("focus", "python · sql · aws"), ("building", "tools people actually use"),
          ("next_stop", "data engineer")]
    for i, (k, v) in enumerate(kv):
        parts.append(
            f'<text x="608" y="{72 + i * 30}" font-family="{MONO}" font-size="14" '
            f'class="rise d{i + 1}"><tspan fill="{t["violet"]}">{k}</tspan>'
            f'<tspan x="706" fill="{t["muted"]}">=</tspan>'
            f'<tspan x="724" fill="{t["text"]}">"{escape(v)}"</tspan></text>'
        )
    # pipeline: flowing line, travelling packets, then nodes on top
    x_start, x_end = x0 + 10, x0 + len(nodes) * node_w + (len(nodes) - 1) * gap - 10
    parts.append(
        f'<line x1="{x_start}" y1="{line_y}" x2="{x_end}" y2="{line_y}" stroke="url(#beam)" '
        f'stroke-width="2" stroke-dasharray="6 8" class="flow" opacity="0.9"/>'
    )
    travel = x_end - x_start
    for i, color in enumerate([t["accent"], t["violet"], t["amber"]]):
        parts.append(
            f'<circle cx="{x_start}" cy="{line_y}" r="4" fill="{color}" class="packet" '
            f'style="animation-delay:{i * 1.6}s;--d:{travel}px"/>'
        )
    for i, label in enumerate(nodes):
        nx = x0 + i * (node_w + gap)
        stroke = t["accent"] if i in (0, len(nodes) - 1) else t["border"]
        parts.append(
            f'<rect x="{nx}" y="{y}" width="{node_w}" height="38" rx="9" fill="{t["card"]}" '
            f'stroke="{stroke}"/><text x="{nx + node_w / 2}" y="{y + 24}" text-anchor="middle" '
            f'font-family="{MONO}" font-size="13" fill="{t["text"]}">'
            f'<tspan fill="{t["muted"]}">{i + 1:02d} </tspan>{label}</text>'
        )
    style = (
        ".cursor{animation:blink 1.1s steps(1) infinite}"
        "@keyframes blink{50%{opacity:0}}"
        ".rise{animation:rise .8s ease-out both}.d1{animation-delay:.15s}.d2{animation-delay:.3s}"
        ".d3{animation-delay:.45s}"
        "@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}"
        ".flow{animation:flow 1s linear infinite}@keyframes flow{to{stroke-dashoffset:-14}}"
        ".packet{animation:travel 4.8s linear infinite both;opacity:0}"
        "@keyframes travel{0%{transform:translateX(0);opacity:0}8%{opacity:1}"
        "92%{opacity:1}100%{transform:translateX(var(--d));opacity:0}}"
    )
    return svg(w, h, "".join(parts), style, "Julio Cesar Santos, Data Engineering at Itaú Unibanco")


def wrap(text: str, limit: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > limit and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line] if line else lines


def card(c: dict, t: dict) -> str:
    w, h = 490, 190
    lang_color = LANG_COLORS.get(c["language"], t["muted"])
    badge_w = len(c["badge"]) * 7 + 18
    parts = [
        f'<defs><linearGradient id="edge" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{t["accent"]}"/><stop offset="1" stop-color="{t["violet"]}"/>'
        f'</linearGradient><clipPath id="r"><rect width="{w}" height="{h}" rx="12"/></clipPath></defs>',
        f'<g clip-path="url(#r)"><rect width="{w}" height="{h}" fill="{t["card"]}"/>'
        f'<rect width="4" height="{h}" fill="url(#edge)"/></g>',
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="12" fill="none" stroke="{t["border"]}"/>',
        f'<circle cx="30" cy="34" r="6" fill="{lang_color}"/>',
        f'<text x="44" y="40" font-family="{SANS}" font-size="18" font-weight="700" '
        f'fill="{t["text"]}">{escape(c["name"])}</text>',
        f'<rect x="{w - 22 - badge_w}" y="21" width="{badge_w}" height="24" rx="12" fill="none" '
        f'stroke="{t["amber"]}"/><text x="{w - 22 - badge_w / 2}" y="37" text-anchor="middle" '
        f'font-family="{MONO}" font-size="11" font-weight="600" fill="{t["amber"]}">{c["badge"]}</text>',
    ]
    for i, line in enumerate(wrap(c["tagline"], 62)[:2]):
        parts.append(
            f'<text x="24" y="{74 + i * 21}" font-family="{SANS}" font-size="14" '
            f'fill="{t["muted"]}">{escape(line)}</text>'
        )
    x = 24
    for tag in c["stack"]:
        tw = len(tag) * 6.6 + 18
        parts.append(
            f'<rect x="{x}" y="128" width="{tw}" height="22" rx="6" fill="{t["chip"]}"/>'
            f'<text x="{x + tw / 2}" y="143" text-anchor="middle" font-family="{MONO}" '
            f'font-size="11" fill="{t["text"]}">{escape(tag)}</text>'
        )
        x += tw + 8
    if c.get("private"):
        meta = [f'<tspan fill="{t["amber"]}">●</tspan> private repo',
                f'<tspan fill="{t["accent"]}">●</tspan> {escape(c["language"].lower())}',
                "in development"]
    else:
        meta = card_meta(c, t)
    parts.append(
        f'<text x="24" y="173" font-family="{MONO}" font-size="12" fill="{t["muted"]}">'
        + "".join(f'<tspan dx="{0 if i == 0 else 18}">{m}</tspan>' for i, m in enumerate(meta))
        + "</text>"
    )
    slug = c["name"].replace(" ", "-")
    return svg(w, h, "".join(parts), "", f'{slug}: {c["tagline"]}')


def card_meta(c: dict, t: dict) -> list[str]:
    meta = [f'<tspan fill="{t["amber"]}">★</tspan> {c["stars"]}']
    if c["downloads"]:
        meta.append(f'<tspan fill="{t["green"]}">↓</tspan> {c["downloads"]} downloads')
    meta.append(f'<tspan fill="{t["accent"]}">●</tspan> {escape(c["language"].lower())}')
    meta.append(f'last push {c["pushed"]}')
    return meta


def run_log(data: dict, t: dict) -> str:
    w, h = 1000, 262
    rows = [
        ("EXTRACT", t["accent"], f"GET api.github.com/users/{USER}/repos",
         f'{data["repos"]} public + {data["private"]} private repos'),
        ("TRANSFORM", t["violet"], "aggregate stars, release downloads, language bytes",
         f'{data["stars"]} stars · {data["downloads"]} downloads'),
        ("LOAD", t["green"], "render dark + light SVGs into assets/", "README refreshed ✔"),
    ]
    parts = [
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>',
        f'<path d="M1 40 H{w-1}" stroke="{t["border"]}"/>',
    ]
    for i, color in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        parts.append(f'<circle cx="{24 + i * 20}" cy="20" r="6" fill="{color}"/>')
    parts.append(
        f'<text x="{w / 2}" y="25" text-anchor="middle" font-family="{MONO}" font-size="12.5" '
        f'fill="{t["muted"]}">pipeline.log · last run {data["run_at"]}</text>'
    )
    for i, (stage, color, action, result) in enumerate(rows):
        y = 74 + i * 30
        parts.append(
            f'<text x="28" y="{y}" font-family="{MONO}" font-size="14" class="line" '
            f'style="animation-delay:{0.25 + i * 0.45}s"><tspan fill="{color}" font-weight="700">'
            f'[{stage}]</tspan><tspan x="160" fill="{t["text"]}">{escape(action)}</tspan>'
            f'<tspan x="{w - 28}" text-anchor="end" fill="{t["muted"]}">{escape(result)}</tspan></text>'
        )
    # language bar
    bar_x, bar_y, bar_w = 28, 190, w - 56
    parts.append(
        f'<text x="28" y="177" font-family="{MONO}" font-size="12" fill="{t["muted"]}">'
        f'languages by bytes across {data["repos"]} public + {data["private"]} private repos '
        f'({data["language_count"]} detected)</text>'
        f'<clipPath id="bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="10" rx="5"/></clipPath>'
        '<g clip-path="url(#bar)" class="grow">'
    )
    x = bar_x
    for name, share in data["languages"]:
        seg = bar_w * share
        color = LANG_COLORS.get(name, t["muted"])
        parts.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{seg + 0.5:.1f}" height="10" fill="{color}"/>')
        x += seg
    parts.append("</g>")
    x = bar_x
    for name, share in data["languages"]:
        label = f"{name} {share * 100:.1f}%"
        color = LANG_COLORS.get(name, t["muted"])
        parts.append(
            f'<circle cx="{x + 5}" cy="{bar_y + 33}" r="5" fill="{color}"/>'
            f'<text x="{x + 15}" y="{bar_y + 37}" font-family="{MONO}" font-size="12" '
            f'fill="{t["text"]}">{escape(label)}</text>'
        )
        x += len(label) * 7.2 + 34
    style = (
        ".line{animation:show .5s ease-out both}"
        "@keyframes show{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}"
        ".grow{animation:grow 1.2s .9s ease-out both;transform-origin:28px 0}"
        "@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
    )
    return svg(w, h, "".join(parts), style, "Profile pipeline run log with GitHub stats")


def load(data: dict) -> None:
    ASSETS.mkdir(exist_ok=True)
    for mode, theme in THEMES.items():
        (ASSETS / f"header-{mode}.svg").write_text(header(theme), encoding="utf-8")
        (ASSETS / f"pipeline-{mode}.svg").write_text(run_log(data, theme), encoding="utf-8")
        for c in data["cards"]:
            (ASSETS / f"card-{c['name'].replace(' ', '-')}-{mode}.svg").write_text(card(c, theme), encoding="utf-8")


def main() -> None:
    data = transform(extract(), extract_private())
    load(data)
    print(f"[load] {data['repos']} repos | {data['stars']} stars | "
          f"{data['downloads']} downloads | {len(data['cards'])} cards")


if __name__ == "__main__":
    main()
