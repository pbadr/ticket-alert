"""Avengers: Doomsday ticket watcher - single run, for GitHub Actions.

Each run checks every cinema that hasn't alerted yet, sends an ntfy alert
when showtimes appear, records that in state.json, and exits. The workflow
commits state.json back to the repo so the next run remembers.
"""

import json
import os
import sys

import requests

CINEMAS = {
    "Cue Cinemas": "https://cuecinemas.com/Browsing/Movies/Details/f-F000001483",
    "Cinestar": "https://cinestar.pk/Browsing/Movies/Details/f-AVENDOO002",
}
NO_SESSIONS = "no sessions scheduled"
MUST_CONTAIN = "doomsday"
BAD_CHECKS_BEFORE_HEADS_UP = 6  # 6 runs x 5 min = ~30 min of unreadable page

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TEST_PING = os.environ.get("TEST_PING", "").lower() == "true"
STATE_FILE = os.environ.get("STATE_FILE", "state.json")


def ascii_only(value):
    """ntfy header values must be plain ASCII."""
    return str(value).encode("ascii", "ignore").decode("ascii")


def notify(title, message, click=None, priority="urgent", tags="ticket"):
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if click:
        headers["Click"] = click
    headers = {k: ascii_only(v) for k, v in headers.items()}
    try:
        r = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"::error::ntfy send failed: {e}")
        return False


def check(url):
    """Return (status, detail). status is 'on_sale', 'waiting' or 'bad'."""
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
    return "on_sale", "SHOWTIMES ARE UP"


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
            print(f"::error::{msg}")
            return 1
        print(f"::warning::{msg} Skipping this scheduled run.")
        return 0  # no failure email every run while setup is unfinished

    state = load_state()
    send_failed = False
    report = []

    for name, url in CINEMAS.items():
        if name in state["alerted"]:
            report.append(f"{name}: already alerted")
            continue

        status, detail = check(url)
        print(f"{name}: {detail}")
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
            print(f"::warning::{name}: page may have changed ({detail}). No alert sent.")
            streak = state["bad_streak"].get(name, 0) + 1
            state["bad_streak"][name] = streak
            if streak == BAD_CHECKS_BEFORE_HEADS_UP:
                notify(
                    f"Checker can't read the {name} page",
                    f"{streak} checks in a row failed ({detail}). The page may have "
                    "changed or be blocking GitHub. Check it manually; you won't get "
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
            "Test ping from GitHub Actions. Checking every 5 min. Current status:\n"
            + "\n".join(report),
            priority="urgent",
            tags="white_check_mark",
        )
        send_failed = send_failed or not ok

    save_state(state)

    all_done = all(name in state["alerted"] for name in CINEMAS)
    set_output("done", "true" if all_done else "false")
    if all_done:
        print("Both cinemas have alerted. The workflow will now disable itself.")

    return 1 if send_failed else 0


if __name__ == "__main__":
    sys.exit(main())
