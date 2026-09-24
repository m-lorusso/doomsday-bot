# Doomsday Bot

Watches Sydney cinemas for **Avengers: Doomsday** (AU release 17 Dec 2026,
previews from 16 Dec) and messages you on Telegram — with **IMAX treated as the
thing that matters**.

- **IMAX on sale** → a loud alert, **pinned to the top of the chat**, followed
  by a second short message so your phone buzzes twice. Every session time is a
  tap-through to seat selection, with a big **BOOK … NOW** link per screen.
- **General on sale** → one loud alert the first time. After that, newly added
  (non-IMAX) sessions arrive as quiet updates, so they never dilute the IMAX
  alert.
- **Daily status** → silent, and it always says where IMAX stands.

Python standard library only — nothing to `pip install`.

## Where things stand (25 Sep 2026)

Doomsday went on sale on 24 Sep — between 3:29 AM and 6:39 AM Sydney time at
Event, a little later at HOYTS. **Neither IMAX screen is selling it yet.**
Neither has released any December programming for any film: IMAX Sydney's
calendar ends 1 Nov and Blacktown's IMAX screen is booked only to 14 Oct.
*Dune: Part Three* also opens 16 Dec and isn't on sale yet either, so the IMAX
screens for release week are still undecided.

## The two IMAX screens

| Screen | Chain | How it's checked |
| --- | --- | --- |
| **IMAX Sydney**, Darling Harbour | Event | `GetSessions?cinemaIds=96` — the venue is IMAX-only |
| **Blacktown IMAX** | HOYTS | `sessions/WESCIN` — only sessions whose `typeId`/`screenName` is IMAX |

IMAX is decided per session, never from a venue's name. Blacktown has an IMAX
screen, but most of its Doomsday sessions are Standard, Xtremescreen or ScreenX.
An earlier version labelled the whole venue "Blacktown (IMAX)" and starred
those sessions as if they were IMAX. That's fixed, and there's a test for it.

HOYTS matches the film by *name*, not a fixed code, so an IMAX version arriving
under a new Vista film code is still caught.

## How often it checks — honestly

| Runner | IMAX | Everything else | Needs |
| --- | --- | --- | --- |
| **This PC** (`watch_imax.ps1`) | **every minute** | on `/check` | PC on and logged in |
| **GitHub Actions** | each run | each run | nothing — but see below |

The workflow asks GitHub for every 5 minutes. **GitHub has actually been
running it about every 3–4 hours** (median gap 215 min across 100 runs, all
successful). Scheduled workflows are low priority and most triggers are
dropped. That's why the on-sale alert on the 24th landed at 6:39 AM rather than
the moment tickets opened. So:

- **The PC watcher is the fast path for IMAX.** Install it once:
  ```powershell
  .\install_local_schedule.ps1
  ```
  Task Scheduler keeps exactly one watcher alive and restarts it within 5
  minutes if it stops. It checks both IMAX screens every minute, answers
  `/check` and `/imax` within a minute, and logs to `local_watch.log`. It uses
  its own `local_state.json`, seeded from `state.json`, so it never fights
  GitHub's copy.
- **GitHub Actions is the backup** for when the PC is off, and sends the daily
  status.

## Commands

Text the bot:

| Command | What it does |
| --- | --- |
| `/imax` | Where both IMAX screens stand right now |
| `/check` | Checks every cinema and reports back (also `/status`, `/now`) |
| `/help` | Lists the commands |

Only messages from `TELEGRAM_CHAT_ID` are acted on; the bot's username is
public. Replies arrive within a minute while the PC watcher runs, otherwise at
GitHub's next run.

## Coverage

**Event (16)** — IMAX Sydney, George Street, Bondi Junction, Parramatta, Castle
Hill, Macquarie, Top Ryde City, Miranda, Hurstville, Burwood, Hornsby,
Liverpool, Campbelltown, Ed Square, Drive In Blacktown, Moonlight Sydney.

**HOYTS (12)** — Blacktown, Broadway, Entertainment Quarter, Chatswood
Westfield, Chatswood Mandarin, Eastgardens, Warringah Mall, Bankstown, Cronulla,
Mt Druitt, Penrith, Wetherill Park.

Not covered: Ritz and Palace (dropped by choice); Reading, Dendy, Orpheum,
United and Roseville (auth-gated or client-rendered — they'd need a headless
browser).

## How each chain is read

**Event** — `GET /Cinemas/GetSessions?cinemaIds=<id>&cinemaIds=<id>...&date=YYYY-MM-DD`.
Repeat `cinemaIds` to ask about several venues at once (a comma-separated list
returns a 500). One request for all 16 venues returns exactly the sessions 16
separate requests would (verified: 215 = 215), in 0.1s instead of 2.6s. `Movies`
only lists films with sessions *on that date*, so the bot probes the release
date, then other on-sale dates from `WATCH_FROM`, **nearest the release first**.
(An earlier version took the *earliest* dates from 1 Nov, and as the calendar
filled up it stopped reaching December — it was missing ~900 Event sessions.)

Event sits behind Cloudflare, which 403s cold requests from datacentre IPs. A
shared cookie jar plus a warm-up request against the site root carries the
`__cf_bm` clearance cookie. A 403 backs off 4s/12s/30s, and a run gives up on
follow-up dates after two consecutive failures rather than spend minutes in
backoff.

**HOYTS** — open JSON API. `/api/movies` maps Vista film codes to names;
`/api/sessions/<venue>` (~150 KB) is one venue's sessions for every date. Twelve
of those replace the 4.8 MB national `/api/sessions` dump. Reading sessions
directly also means no reliance on the `onSale` flag — on the 24th it lagged the
real listings by hours.

A full check of all 28 venues takes about 10 seconds.

## Setup

1. **Telegram**: [@BotFather](https://t.me/BotFather) → `/newbot` → token.
   Message the bot once, then get your chat id from
   `https://api.telegram.org/bot<TOKEN>/getUpdates`. Put both in `.env` (see
   `.env.example`).
2. **GitHub**: push the repo (public, so Actions minutes are free), then add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` under Settings → Secrets and
   variables → Actions.
3. **This PC**: `.\install_local_schedule.ps1`.

## Testing

```bash
python -m unittest discover -s tests -v   # offline: IMAX detection, pinning, alerts, DST...
python -m bot.main --dry-run              # live check; prints instead of sending, saves nothing
python -m bot.main --test-imax            # sends a sample IMAX alert, clearly marked TEST
python -m bot.main --test-alert           # proves Telegram delivery
```

To see the real IMAX alert render against live data, point it at a film that's
in IMAX now. At the time of writing that's *Avengers: Endgame Encore*, on both
screens:

```bash
STATE_FILE=/tmp/s.json MOVIE_MATCH=endgame MOVIE_TITLE="Avengers: Endgame Encore" \
  RELEASE_DATE=2026-09-26 WATCH_FROM=2026-09-25 python -m bot.main --dry-run
```

## Configuration

Everything in [`bot/config.py`](bot/config.py) can be overridden by an
environment variable of the same name. The ones you might touch:

| Variable | Default | Meaning |
| --- | --- | --- |
| `IMAX_POLL_SECONDS` | `60` | IMAX check interval in the watch loop |
| `FULL_CHECK_MINUTES` | `15` | Full check interval in the loop (not in `--imax-only`) |
| `WATCH_FROM` | `2026-12-14` | Event dates from here on get probed |
| `RELEASE_DATE` | `2026-12-17` | Probed first every time |
| `HEARTBEAT_HOURS` | `24` | Daily status cadence; `0` disables (the PC watcher sets 0) |
| `IMAX_SESSIONS_LISTED` | `12` | Sessions per screen in the IMAX alert |
| `MAX_SESSIONS_LISTED` / `MAX_CINEMAS_LISTED` | `6` / `8` | Caps for the general alert |

Venue lists live in [`bot/providers/event.py`](bot/providers/event.py) and
[`bot/providers/hoyts.py`](bot/providers/hoyts.py); each also has a `REGIONAL`
list if you'd travel.

## State

`state.json` (GitHub's) and `local_state.json` (the PC's) record which sessions
you've already been told about, whether the big on-sale announcement has gone
out, the latest status of each chain and IMAX screen, and the Telegram inbox
offset. GitHub commits its copy back after each run. There's no run timestamp
in it on purpose — that would mean a commit every run.
