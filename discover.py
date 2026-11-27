"""One-off: how Universal Cinemas pages show sessions per cinema (Lahore 8888 / Multan 9999)."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0"}
B = "https://universalcinemas.com"
PAGES = {
    "doomsday": f"{B}/browsing/Movies/Details/m-HO00001519",
    "spiderman": f"{B}/browsing/Movies/Details/h-HO00001418",
    "wildwood": f"{B}/browsing/Movies/Details/h-HO00001597",
    "lahore-cinema": f"{B}/browsing/Cinemas/Details/8888",
}
for name, url in PAGES.items():
    r = requests.get(url, headers=UA, timeout=30)
    h = r.text
    low = h.lower()
    print(f"\n######## {name} {url} -> {r.status_code} len={len(h)} final={r.url}")
    print("no-sessions text:", "no sessions scheduled" in low, "| doomsday:", "doomsday" in low,
          "| lahore count:", low.count("lahore"), "| multan count:", low.count("multan"),
          "| 8888 count:", h.count("8888"), "| 9999 count:", h.count("9999"))
    links = sorted(set(re.findall(r"""href=["']([^"']*(?:[Tt]icketing|[Ss]ession|cinemacode|CinemaId|cinemaId)[^"']*)""", h)))
    print(f"session-ish links ({len(links)}):")
    for l in links[:12]:
        print("   ", l)
    for word in ("lahore", "multan"):
        for m in list(re.finditer(word, low))[:4]:
            print(f"  [{word}] ...{re.sub(r'\s+', ' ', h[max(0, m.start()-250):m.end()+250])}...")
    m = re.search(r"no sessions scheduled", low)
    if m:
        print("  [no-sessions context] ...", re.sub(r"\s+", " ", h[max(0, m.start()-600):m.end()+200]))
    # first session block raw
    m = re.search(r"(?:[Tt]icketing|txtSessionId|cinemacode)", h)
    if m:
        print("  [first session context] ...", re.sub(r"\s+", " ", h[max(0, m.start()-1500):m.end()+700]))
