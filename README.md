# Doomsday ticket watch

Sends a phone notification (via ntfy) when Avengers: Doomsday showtimes
appear on the Cue Cinemas or Cinestar (Lahore) booking pages. Runs free on
GitHub Actions about every 5 minutes, so no PC needs to stay on.

## Files

```
check.py                      the checker (one pass per run)
state.json                    remembers which cinemas already alerted
.github/workflows/watch.yml   the schedule
```

## Setup

**Keep this repo public.** Public repos get unlimited free Actions minutes.
A private repo on the free plan would run out before 18 Dec
(288 runs a day x 1 billed minute each, against 2,000 included minutes a month).

1. **Add your ntfy topic as a secret** so it stays hidden in the public repo:
   *Settings > Secrets and variables > Actions > New repository secret*
   - Name: `NTFY_TOPIC`
   - Value: the topic your phone's ntfy app is subscribed to

   Until it's set, scheduled runs skip quietly (no failure emails).

2. **Test it**: *Actions* tab (enable workflows if asked) > *Doomsday ticket watch*
   > *Run workflow*. Within a minute your phone should get
   "Doomsday checker test" showing `no sessions yet` for both cinemas.
   - If it shows `HTTP 403` or `'doomsday' missing` instead, that cinema is
     blocking GitHub's servers. Use Distill.io for that one.
   - No ping and a red run: open the run log. "NTFY_TOPIC is not set" means
     step 1 is missing.

That's it. The schedule starts on its own.

## How it behaves

- **Every ~5 min**: checks each cinema that hasn't alerted yet. No notification
  unless something happens.
- **Showtimes appear**: urgent ntfy alert with a tap-to-book link. That cinema
  is then skipped on later runs.
- **Both alerted**: the workflow disables itself.
- **Page unreadable** (not HTTP 200, or "doomsday" missing): logged as a warning,
  never sent as a ticket alert. After 6 bad checks in a row (about 30 min) you get
  one normal-priority "Checker can't read..." heads-up, since nobody watches the logs.
- **ntfy unreachable**: the run is marked failed (GitHub emails you) and the alert
  is retried on the next run.
- **Test ping**: on manual *Run workflow*, and whenever a change to `check.py`
  or the workflow is pushed (so every deploy confirms itself). Never on
  scheduled runs.

## Limits worth knowing

- GitHub may start scheduled runs late when it's busy, sometimes by 30+ minutes.
  Fine for this, but not to-the-minute.
- Re-run the check by hand at any time with *Run workflow*.
- To reset (e.g. to watch again), set `state.json` back to
  `{"alerted": [], "bad_streak": {}}` and re-enable the workflow in the Actions tab.
