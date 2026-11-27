"""Avengers: Doomsday ticket watcher - single run.

Each run checks every cinema that hasn't alerted yet, sends an ntfy alert
when showtimes appear, records that in state.json, and exits. On GitHub
Actions the workflow commits state.json back to the repo so the next run
remembers; on a server, cron runs it (see setup-vps.sh).
"""

import json
import os
import re
import socket
import sys
from datetime import datetime, timedelta, timezone

import requests
import urllib3.util.connection as urllib3_connection

CINEMAS = {
    "Cue Cinemas": "https://cuecinemas.com/Browsing/Movies/Details/f-F000001483",
    "Cinestar": "https://cinestar.pk/Browsing/Movies/Details/f-AVENDOO002",
    # Universal Cinemas runs the same Vista system, but its site covers two
    # cinemas: Emporium Mall Lahore (code 8888) and The Grand Mall Multan (9999).
    "Universal Cinemas Lahore": "https://universalcinemas.com/browsing/Movies/Details/m-HO00001519",
}
# For sites listing several cinemas: only sessions at this cinema code count.
# Each session's booking link carries it (visSelectTickets.aspx?cinemacode=8888),
# and each cinema's block links to /browsing/Cinemas/Details/<code>.
ONLY_CINEMA_CODE = {
    "Universal Cinemas Lahore": "8888",
}
NO_SESSIONS = "no sessions scheduled"
MUST_CONTAIN = "doomsday"
BAD_CHECKS_BEFORE_HEADS_UP = 6  # 6 runs x 5 min = ~30 min of unreadable page

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TEST_PING = os.environ.get("TEST_PING", "").lower() == "true"
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"
SOURCE = "GitHub Actions" if ON_GITHUB else socket.gethostname()
PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan time (no daylight saving)


def log(msg, level=None):
    """Print one log line.

    On a server each line starts with the date and time in Pakistan time, so
    `tail ~/doomsday.log` shows when the last check ran. On GitHub Actions the
    log viewer adds its own timestamps, and warnings/errors use GitHub's
    ::warning:: / ::error:: syntax so they show up as annotations on the run.
    """
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


def check(url, cinema_code=None):
    """Return (status, detail). status is 'on_sale', 'waiting' or 'bad'.

    With cinema_code, only sessions at that cinema count as on sale.
    """
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    except requests.RequestException as e:
        return "bad", f"request failed ({type(e).__name__})"
    html = r.text.lower()
    if r.status_code != 200 or MUST_CONTAIN not in html:
        found = "found" if MUST_CONTAIN in html else "missing"
        return "bad", f"HTTP {r.status_code}, '{MUST_CONTAIN}' {found}"
    if NO_SESSIONS in html:
        return "waiting", "no sessions yet"
    if cinema_code is None:
        return "on_sale", "SHOWTIMES ARE UP"
    code = re.escape(cinema_code)
    if re.search(rf"cinemacode={code}(?!\d)", html) or re.search(rf"/cinemas/details/{code}(?!\d)", html):
        return "on_sale", "SHOWTIMES ARE UP"
    if "visselecttickets" in html or "/cinemas/details/" in html:
        return "waiting", "showtimes listed, but only at other cinemas so far"
    return "bad", "no-sessions text gone but no cinema showtimes found (page may have changed)"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("alerted", [])
    state.setdefault("bad_streak", {})
    return state


def save_state(state):
    # No timestamp here on purpose: the file (and the repo) only changes
    # when something actually happens, so there's no commit every run.
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def set_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main():
    if not NTFY_TOPIC:
        msg = "NTFY_TOPIC is not set (add it as a repository secret)."
        if TEST_PING:  # manual/deploy run: fail loudly so the setup problem is obvious
            log(msg, "error")
            return 1
        log(f"{msg} Skipping this scheduled run.", "warning")
        return 0  # no failure email every run while setup is unfinished

    state = load_state()
    send_failed = False
    report = []

    for name, url in CINEMAS.items():
        if name in state["alerted"]:
            log(f"{name}: already alerted, not checking again")
            report.append(f"{name}: already alerted")
            continue

        status, detail = check(url, ONLY_CINEMA_CODE.get(name))
        log(f"{name}: {detail}")
        report.append(f"{name}: {detail}")

        if status == "on_sale":
            ok = notify(
                f"Doomsday tickets are out at {name}",
                f"Avengers: Doomsday showtimes are now listed at {name}. Tap to book.",
                click=url,
            )
            if ok:
                state["alerted"].append(name)  # stop checking this cinema
                state["bad_streak"][name] = 0
            else:
                send_failed = True  # not marked, so the next run tries again

        elif status == "bad":
            log(f"{name}: page may have changed ({detail}). No alert sent.", "warning")
            streak = state["bad_streak"].get(name, 0) + 1
            state["bad_streak"][name] = streak
            if streak == BAD_CHECKS_BEFORE_HEADS_UP:
                notify(
                    f"Checker can't read the {name} page",
                    f"{streak} checks in a row failed ({detail}). The page may have "
                    f"changed or be blocking {SOURCE}. Check it manually; you won't get "
                    "a ticket alert for this cinema until it's readable again.",
                    click=url,
                    priority="default",
                    tags="warning",
                )

        else:  # waiting
            state["bad_streak"][name] = 0

    if TEST_PING:
        # Same urgent priority as the real alert, so you hear what it sounds like.
        ok = notify(
            "Doomsday checker test",
            f"Test ping from {SOURCE}. Current status:\n" + "\n".join(report),
            priority="urgent",
            tags="white_check_mark",
        )
        send_failed = send_failed or not ok

    save_state(state)

    all_done = all(name in state["alerted"] for name in CINEMAS)
    set_output("done", "true" if all_done else "false")
    if all_done:
        if ON_GITHUB:
            log("All cinemas have alerted. The workflow will now disable itself.")
        else:
            log("All cinemas have alerted. Nothing left to check; you can remove the cron job.")

    return 1 if send_failed else 0


if __name__ == "__main__":
    sys.exit(main())
