"""Avengers: Doomsday ticket watcher for Nueplex and Cinepax - single run.

Separate from check.py (Cue / Cinestar): its own ntfy topic, state file and
log. Run it from cron on a server (see setup-vps.sh with WATCHER=nueplex-cinepax).

How "tickets are out" is detected:
  Nueplex  The homepage's showtime filter has an "All Movies" dropdown that
           lists the films with bookable showtimes. Doomsday appearing there
           means tickets are on sale. One alert, then Nueplex is done.
  Cinepax  web.cinepax.com loads its listings from a JSON API. For each
           cinema, Doomsday showing up in its advance-booking list, or in its
           now-showing list with sessions, means tickets are on sale there.
           You get one alert per run listing the cinemas that newly opened,
           so more alerts can follow as other cinemas open.
           Backup: Doomsday is already in Cinepax's coming-soon list with a
           "hasFutureSessions" flag; if that turns true but no cinema lists it
           yet, you get a one-off heads-up.
"""

import json
import os
import re
import socket
import sys
from datetime import datetime, timedelta, timezone

import requests
import urllib3.util.connection as urllib3_connection

TITLE_MATCH = "doomsday"
NUEPLEX_URL = "https://www.nueplex.com/"
CINEPAX_API = "https://web.cinepax.com/api"
CINEPAX_BOOKING_URL = "https://web.cinepax.com/pages/movies.html"
BAD_CHECKS_BEFORE_HEADS_UP = 6  # 6 runs x 5 min = ~30 min unreadable

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130 Safari/537.36"}
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TEST_PING = os.environ.get("TEST_PING", "").lower() == "true"
STATE_FILE = os.environ.get("STATE_FILE", "state-nueplex-cinepax.json")
ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"
SOURCE = "GitHub Actions" if ON_GITHUB else socket.gethostname()
PKT = timezone(timedelta(hours=5), "PKT")


# ---------------------------------------------------------------- helpers

def log(msg, level=None):
    if ON_GITHUB:
        print(f"::{level}::{msg}" if level else msg, flush=True)
    else:
        stamp = datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S PKT")
        prefix = f"{level.upper()}: " if level else ""
        print(f"[{stamp}] {prefix}{msg}", flush=True)


def ascii_only(value):
    """ntfy header values must be plain ASCII."""
    return str(value).encode("ascii", "ignore").decode("ascii")


def _post_ntfy(message, headers, ipv4_only):
    original = urllib3_connection.allowed_gai_family
    if ipv4_only:
        urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
    try:
        return requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode("utf-8"),
                             headers=headers, timeout=20)
    finally:
        urllib3_connection.allowed_gai_family = original


def notify(title, message, click=None, priority="urgent", tags="ticket"):
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if click:
        headers["Click"] = click
    headers = {k: ascii_only(v) for k, v in headers.items()}
    try:
        try:
            # ntfy.sh limits anonymous senders per address. Over IPv6 that
            # address block can be shared with other customers of the same
            # VPS provider, who can use up the quota; IPv4 is usually yours
            # alone. Fall back to the default route if there's no IPv4.
            r = _post_ntfy(message, headers, ipv4_only=True)
        except requests.ConnectionError:
            r = _post_ntfy(message, headers, ipv4_only=False)
        if r.status_code >= 400:
            log(f"ntfy send failed: HTTP {r.status_code} {r.text.strip()[:200]}", "error")
            return False
        return True
    except requests.RequestException as e:
        log(f"ntfy send failed: {e}", "error")
        return False


def fetch(url, want_json=False):
    """GET with one retry on timeout/connection error. Returns body or None."""
    for attempt in (1, 2):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code != 200:
                return None
            return r.json() if want_json else r.text
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                return None
        except (requests.RequestException, ValueError):
            return None
    return None


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("nueplex_alerted", False)
    state.setdefault("cinepax_alerted", [])       # cinema ids already alerted
    state.setdefault("cinepax_flag_alerted", False)
    state.setdefault("bad_streak", {})
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def pretty_cinema(name):
    """'CINEPAX AMANAH MALL' -> 'Amanah Mall'."""
    name = re.sub(r"^\s*cinepax\s+", "", name or "", flags=re.I).strip()
    return name.title() if name.isupper() else name


def version_of(title):
    """'Avengers: Doomsday (3D Urdu)' -> '3D Urdu'."""
    m = re.search(r"\(([^)]*)\)\s*$", title or "")
    return m.group(1).strip() if m else (title or "").strip()


# ---------------------------------------------------------------- Nueplex

def check_nueplex():
    """Return (status, detail, matches). status: on_sale / waiting / bad."""
    html = fetch(NUEPLEX_URL)
    if html is None:
        return "bad", "homepage didn't load", []
    m = re.search(r"<select[^>]*id=[\"']dateShowMovie[\"'][^>]*>([\s\S]*?)</select>", html, re.I)
    if not m:
        return "bad", "showtime movie list not found (page may have changed)", []
    options = re.findall(r"<option[^>]*value=[\"']?(\d+)[\"']?[^>]*>([\s\S]*?)</option>", m.group(1), re.I)
    titles = [re.sub(r"\s+", " ", t).strip() for _, t in options]
    if not titles:
        return "bad", "showtime movie list is empty (page may have changed)", []
    matches = [t for t in titles if TITLE_MATCH in t.lower()]
    if matches:
        return "on_sale", "SHOWTIMES ARE UP: " + ", ".join(matches), matches
    return "waiting", f"not in showtimes yet ({len(titles)} films listed)", []


# ---------------------------------------------------------------- Cinepax

def has_sessions(movie):
    if movie.get("hasFutureSessions"):
        return True
    screens = movie.get("screens") or {}
    return any((s or {}).get("sessions") for s in screens.values() if isinstance(s, dict))


def check_cinepax():
    """Return (status, detail, open_at, flagged).

    open_at: {cinema_id: (pretty name, [versions])} where Doomsday is bookable.
    flagged: True if the coming-soon list says Doomsday has future sessions.
    """
    cinemas = fetch(f"{CINEPAX_API}/cinemas", want_json=True)
    upcoming = fetch(f"{CINEPAX_API}/upcoming", want_json=True)
    if not isinstance(cinemas, list) or not cinemas:
        return "bad", "cinema list didn't load", {}, False
    if not isinstance(upcoming, list):
        return "bad", "coming-soon list didn't load", {}, False

    in_upcoming = [m for m in upcoming if TITLE_MATCH in str(m.get("title", "")).lower()]
    flagged = any(m.get("hasFutureSessions") for m in in_upcoming)

    open_at, ok_requests, failed = {}, 0, 0
    for c in cinemas:
        cid = str(c.get("id") or c.get("cinemaId") or "")
        if not cid:
            continue
        name = pretty_cinema(c.get("name") or cid)
        for path, listing_counts in (("advance-booking", True), ("movies", False)):
            data = fetch(f"{CINEPAX_API}/{path}?cinemaId={cid}", want_json=True)
            if not isinstance(data, list):
                failed += 1
                continue
            ok_requests += 1
            for mv in data:
                title = str(mv.get("title", ""))
                if TITLE_MATCH not in title.lower():
                    continue
                bookable = has_sessions(mv) or (listing_counts and mv.get("allowTicketSales", True))
                if bookable:
                    versions = open_at.setdefault(cid, (name, []))[1]
                    if version_of(title) not in versions:
                        versions.append(version_of(title))

    if ok_requests == 0:
        return "bad", "no cinema listings loaded", {}, flagged
    if failed:
        log(f"Cinepax: {failed} cinema listing request(s) failed this run", "warning")
    if open_at:
        names = ", ".join(n for n, _ in open_at.values())
        return "on_sale", f"BOOKABLE at {len(open_at)} cinema(s): {names}", open_at, flagged
    if not in_upcoming:
        return "bad", "Doomsday not in coming soon and not bookable anywhere (listing may have changed)", {}, flagged
    if flagged:
        return "waiting", "coming-soon list says sessions exist, but no cinema lists them yet", {}, flagged
    return "waiting", f"not bookable yet (in coming soon as {len(in_upcoming)} versions)", {}, flagged


# ---------------------------------------------------------------- main

def handle_bad(state, name, detail, click):
    log(f"{name}: can't check ({detail}). No alert sent.", "warning")
    streak = state["bad_streak"].get(name, 0) + 1
    state["bad_streak"][name] = streak
    if streak == BAD_CHECKS_BEFORE_HEADS_UP:
        notify(f"Checker can't read {name}",
               f"{streak} checks in a row failed ({detail}). The site may have changed or be "
               f"blocking {SOURCE}. Check it manually; you won't get a ticket alert for "
               f"{name} until it's readable again.",
               click=click, priority="default", tags="warning")


def main():
    if not NTFY_TOPIC:
        log("NTFY_TOPIC is not set.", "error")
        return 1

    state = load_state()
    send_failed = False
    report = []

    # Nueplex
    if state["nueplex_alerted"]:
        log("Nueplex: already alerted, not checking again")
        report.append("Nueplex: already alerted")
    else:
        status, detail, matches = check_nueplex()
        log(f"Nueplex: {detail}")
        report.append(f"Nueplex: {detail}")
        if status == "on_sale":
            if notify("Doomsday tickets are out at Nueplex",
                      "Showtimes now listed at Nueplex: " + ", ".join(matches) + ". Tap to book.",
                      click=NUEPLEX_URL):
                state["nueplex_alerted"] = True
            else:
                send_failed = True
            state["bad_streak"]["Nueplex"] = 0
        elif status == "bad":
            handle_bad(state, "Nueplex", detail, NUEPLEX_URL)
        else:
            state["bad_streak"]["Nueplex"] = 0

    # Cinepax (keeps checking, so cinemas that open later also alert)
    status, detail, open_at, flagged = check_cinepax()
    log(f"Cinepax: {detail}")
    report.append(f"Cinepax: {detail}")
    if status == "bad":
        handle_bad(state, "Cinepax", detail, CINEPAX_BOOKING_URL)
    else:
        state["bad_streak"]["Cinepax"] = 0
        new = {cid: v for cid, v in open_at.items() if cid not in state["cinepax_alerted"]}
        if new:
            first = not state["cinepax_alerted"]
            lines = [f"{name} ({', '.join(vers)})" for name, vers in new.values()]
            title = ("Doomsday tickets are out at Cinepax" if first
                     else "Doomsday tickets: more Cinepax cinemas open")
            body = "Bookable at: " + "; ".join(lines) + ". Tap to book."
            if notify(title, body, click=CINEPAX_BOOKING_URL):
                state["cinepax_alerted"].extend(new.keys())
            else:
                send_failed = True
        elif flagged and not open_at and not state["cinepax_flag_alerted"]:
            if notify("Cinepax may have opened Doomsday bookings",
                      "Cinepax's coming-soon list now says Doomsday has sessions, but no cinema "
                      "lists them yet. Worth checking the site.",
                      click=CINEPAX_BOOKING_URL, priority="high"):
                state["cinepax_flag_alerted"] = True
            else:
                send_failed = True

    if TEST_PING:
        ok = notify("Nueplex/Cinepax checker test",
                    f"Test ping from {SOURCE}. Current status:\n" + "\n".join(report),
                    priority="urgent", tags="white_check_mark")
        send_failed = send_failed or not ok

    save_state(state)
    return 1 if send_failed else 0


if __name__ == "__main__":
    sys.exit(main())
