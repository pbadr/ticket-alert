"""One-off round 2: JSON shapes for Cinepax, showtime request for Nueplex."""
import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
CP = "https://web.cinepax.com"


def show(label, url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=30, **kw)
    except Exception as e:
        print(f"\n### {label} {url} ERROR {e}")
        return None
    print(f"\n### {label} {url} -> {r.status_code} {r.headers.get('content-type')} len={len(r.text)}")
    try:
        data = r.json()
    except Exception:
        print(r.text[:800])
        return None
    if isinstance(data, list):
        print(f"list of {len(data)}")
        for item in data[:2]:
            print(json.dumps(item, ensure_ascii=False)[:2500])
        if data and isinstance(data[0], dict):
            for item in data:
                print("  -", {k: item.get(k) for k in ("id", "filmCode", "title", "name", "city", "cinemaId", "releaseDate", "status") if k in item})
    else:
        print(json.dumps(data, ensure_ascii=False)[:3000])
    print("contains 'doomsday':", "doomsday" in r.text.lower(), "| 'avengers':", "avengers" in r.text.lower())
    return data


cinemas = show("CINEMAS", f"{CP}/api/cinemas") or []
show("UPCOMING", f"{CP}/api/upcoming")
show("SETTINGS(defaultCinemaId)", f"{CP}/api/cms/settings")
first_movie = None
for c in cinemas[:20]:
    cid = c.get("id") or c.get("cinemaId")
    mv = show(f"MOVIES {c.get('name')}", f"{CP}/api/movies?cinemaId={cid}")
    ab = show(f"ADVANCE {c.get('name')}", f"{CP}/api/advance-booking?cinemaId={cid}")
    if not first_movie and isinstance(mv, list) and mv:
        first_movie = (cid, mv[0])
if first_movie:
    cid, m = first_movie
    code = m.get("filmCode") or m.get("id")
    show("SHOWTIMES sample", f"{CP}/api/showtimes?filmCode={code}&cinemaId={cid}")
    show("MOVIE detail sample", f"{CP}/api/movie/{code}?cinemaId={cid}")

# ---- Nueplex
print("\n\n######## NUEPLEX")
r = requests.get("https://www.nueplex.com/", headers=UA, timeout=30)
html = r.text
m = re.search(r"function\s+generateQueryStr[\s\S]{0,1500}", html)
print("generateQueryStr:", m.group(0) if m else "NOT FOUND")
for blk in re.findall(r"<script(?![^>]*src)[^>]*>([\s\S]*?)</script>", html, re.I):
    if "showtime.html" in blk:
        print("---- inline block with showtime.html (first 5000 chars):")
        print(blk[:5000])
        break
opts = re.findall(r'<select name="movie" id="dateShowMovie">([\s\S]*?)</select>', html)
print("movie select:", re.sub(r"\s+", " ", opts[0])[:800] if opts else None)
movie_ids = re.findall(r'<option value="(\d+)"', opts[0]) if opts else []
s = requests.Session()
s.headers.update(UA)
s.get("https://www.nueplex.com/", timeout=30)
for data in (
    {"branch": "All", "cinema": "All", "movie": "All", "date": ""},
    {"branch": "1", "cinema": "All", "movie": movie_ids[0] if movie_ids else "All", "date": ""},
):
    try:
        rr = s.post("https://www.nueplex.com/showtime.html", data=data, timeout=30,
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.nueplex.com/"})
        print(f"\nPOST showtime.html {data} -> {rr.status_code} len={len(rr.text)}")
        print(re.sub(r"\s+", " ", rr.text)[:2500])
    except Exception as e:
        print("POST error", e)
for data in ({"branch": 1}, {"branch": 2}):
    rr = s.post("https://www.nueplex.com/branch", data=data, timeout=30,
                headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.nueplex.com/"})
    print(f"\nPOST branch {data} -> {rr.status_code} len={len(rr.text)}: {re.sub(chr(10), ' ', rr.text)[:800]}")
