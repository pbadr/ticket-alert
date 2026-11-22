"""One-off: find how Nueplex and Cinepax load movies/showtimes (temporary branch)."""
import re
import sys
from urllib.parse import urljoin

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
PAGES = [
    "https://www.nueplex.com/",
    "https://www.nueplex.com/movie/Wildwood.html",
    "https://web.cinepax.com/",
    "https://web.cinepax.com/pages/movies.html",
]
URL_RE = re.compile(r"""(?:https?:)?//[^\s"'<>()\\]+|/[A-Za-z0-9_\-./]*(?:api|Api|API|ajax|Ajax|php|json|aspx|ashx|svc)[A-Za-z0-9_\-./?=&]*""")
CALL_RE = re.compile(r"(fetch\s*\(|\$\.(?:ajax|get|post|getJSON)\s*\(|axios[.(]|XMLHttpRequest|\.open\s*\(\s*['\"](?:GET|POST)|baseURL|BASE_URL|apiUrl|API_URL|endpoint)", re.I)


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=30)
        return r.status_code, r.text, r.headers.get("content-type", "")
    except Exception as e:
        return None, f"ERROR {e}", ""


def snippets(text, regex, width=160, limit=40):
    out = []
    for m in regex.finditer(text):
        s = max(0, m.start() - width)
        out.append(text[s:m.end() + width].replace("\n", " "))
        if len(out) >= limit:
            break
    return out


seen_js = set()
for page in PAGES:
    code, html, ctype = get(page)
    print(f"\n######## PAGE {page} -> {code} {ctype} len={len(html)}")
    if code is None:
        print(html)
        continue
    scripts = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html, re.I)
    print("SCRIPT SRCS:", *scripts, sep="\n  ")
    print("FORMS/ACTIONS:", re.findall(r"<form[^>]*>", html, re.I)[:10])
    print("SELECTS:")
    for sel in re.findall(r"<select[\s\S]{0,3000}?</select>", html, re.I)[:6]:
        print("  ", re.sub(r"\s+", " ", sel)[:1500])
    print("URL-LIKE (unique):")
    for u in sorted(set(URL_RE.findall(html)))[:120]:
        print("  ", u)
    inline = re.findall(r"<script(?![^>]*src)[^>]*>([\s\S]*?)</script>", html, re.I)
    print(f"INLINE SCRIPTS: {len(inline)}")
    for i, s in enumerate(inline):
        hits = snippets(s, CALL_RE, 200, 15)
        if hits:
            print(f"  -- inline #{i} (len {len(s)}) calls:")
            for h in hits:
                print("     ", h[:600])
    for low in ("coming soon", "comingsoon", "advance", "doomsday", "avengers"):
        idx = html.lower().find(low)
        print(f"FIRST '{low}':", idx, re.sub(r"\s+", " ", html[max(0, idx - 300):idx + 500]) if idx >= 0 else "")
    for src in scripts:
        js = urljoin(page, src)
        if js in seen_js or any(x in js for x in ("jquery", "bootstrap", "google", "gtag", "facebook", "fontawesome", "swiper", "slick", "owl.carousel", "analytics", "cdn.jsdelivr", "cdnjs")):
            continue
        seen_js.add(js)
        c, body, t = get(js)
        print(f"\n  ==== JS {js} -> {c} len={len(body)}")
        if c != 200:
            continue
        for u in sorted(set(URL_RE.findall(body)))[:80]:
            print("     URL:", u)
        for h in snippets(body, CALL_RE, 220, 25):
            print("     CALL:", h[:700])
sys.stdout.flush()
