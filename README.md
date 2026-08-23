# Doomsday Bot

Watches Sydney cinemas and pings you on Telegram the moment **Avengers:
Doomsday** (AU release 17 Dec 2026) becomes bookable — with session times,
screen type, seats left, and a direct booking link.

Runs free on GitHub Actions every 5 minutes. Python standard library only —
no dependencies, no browser automation, nothing to `pip install`.

## Coverage

| Chain | Sydney venues | Signal | Detail in the alert |
| --- | --- | --- | --- |
| **Event** | 16, incl. **IMAX Sydney** | per-venue session API | times, screen, seats left, booking link |
| **HOYTS** | 12, incl. **IMAX Blacktown** | `onSale` flag + full session dump | times, screen, booking link |

Both Sydney IMAX screens are covered, and IMAX sessions are individually
identifiable — Event reports `ScreenTypeName: IMAX`, HOYTS reports
`typeId: IMAX` on screen `IMAX 01`.

**Event** — IMAX Sydney, George Street, Bondi Junction, Parramatta, Castle Hill,
Macquarie, Top Ryde City, Miranda, Hurstville, Burwood, Hornsby, Liverpool,
Campbelltown, Ed Square, Drive In Blacktown, Moonlight Sydney.

**HOYTS** — Blacktown (IMAX), Broadway, Entertainment Quarter, Chatswood
Westfield, Chatswood Mandarin, Eastgardens, Warringah Mall, Bankstown, Cronulla,
Mt Druitt, Penrith, Wetherill Park.

### Not covered

Ritz Randwick and Palace (Central, Norton St, Moore Park) were dropped by
choice — small venues that won't be first to open a Marvel tentpole, and
neither could report actual session times, only a "it's bookable" flag.

Reading (Rouse Hill, Auburn), Dendy Newtown, Hayden Orpheum, United and
Roseville aren't reachable: Reading's backend sits behind an authenticated
gateway, and the others render entirely client-side, so there's no data to read
over plain HTTP. Covering them would mean running a headless browser on every
check — a large jump in fragility and runtime.

## How each signal works

**Event** — the session picker calls
`GET /Cinemas/GetSessions?cinemaIds=<id>&date=YYYY-MM-DD`. It returns `Movies`
(with `CinemaModels[].Sessions[]`, each carrying `StartTime`, `ScreenTypeName`,
`SeatsAvailable` and a `BookingUrl`) plus `Dates` — the venue's *entire* on-sale
calendar. Each run probes `RELEASE_DATE`, then re-probes any on-sale date at or
after `WATCH_FROM`, which is what saves you if the release shifts a day or
previews open on the 16th. Repeat the param for multiple venues
(`cinemaIds=15&cinemaIds=64`); a comma-separated list returns a 500.

**HOYTS** — an open, unauthenticated API. `/api/movies` (~195 KB) carries an
`onSale` boolean per film; `/api/sessions` (~4.8 MB) is every session in the
country and ignores query filters. So the cheap flag drives every run, and the
big dump is pulled only when that flag flips — plus one forced sweep every
`DEEP_SWEEP_HOURS` in case the flag lags reality. Note a film's `vistaId` can be
comma-separated (`HO00008129,HO00011223`); sessions match on either.

### Cloudflare and the 403s

Event sits behind Cloudflare, which intermittently 403s a cold request coming
from a datacentre IP — i.e. every GitHub Actions runner. It showed up as
`IMAX Sydney: HTTP Error 403: Forbidden` roughly one run in seven, and always
IMAX Sydney, purely because it's first in the venue list and so wore the
challenge for everyone else.

Two things fix it: [`bot/http.py`](bot/http.py) keeps a shared cookie jar so the
`__cf_bm` clearance cookie is reused across a run, and each provider warms up
against the site root first so that challenge lands somewhere harmless. A 403
also backs off 4s/12s/30s rather than the generic 1s/2s, because a Cloudflare
hold outlasts an immediate retry.

Partial failures no longer raise an alert. One venue out of sixteen glitching
is noise; it's reported in the daily update as `15/16 venues` naming the one
that didn't answer. The error alert now fires only when a chain returns
*nothing at all*, which is what an actual outage or a real block looks like.

## Setup

### 1. Telegram

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Send your new bot any message (it can't message you until you've talked to it).
3. Get your chat ID from
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` → `result[0].message.chat.id`.

Copy `.env.example` to `.env`, fill both in, then:

```bash
powershell -File run_once.ps1 --test-alert
```

### 2. GitHub

```bash
git remote add origin https://github.com/<you>/doomsday-bot.git
```

```bash
git add -A && git commit -m "Sydney-wide Doomsday ticket watcher" && git push -u origin main
```

Then **Settings → Secrets and variables → Actions → New repository secret**, for
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

Make the repo **public** — Actions minutes are unlimited for public repos, and a
5-minute schedule is roughly 8,600 runs/month against a 2,000-minute private
free tier. Nothing sensitive is in the code; credentials live in Secrets.

Kick off the first run by hand from the **Actions** tab to confirm it's green.

### 3. Optional: a second pair of eyes from this PC

```powershell
.\install_local_schedule.ps1
```

Registers a Task Scheduler job every 15 minutes. It only runs while the machine
is on, which is why Actions stays primary.

## Talking to the bot

Text the bot in Telegram:

| Command | What it does |
| --- | --- |
| `/check` | Runs a full check now and reports back. Also `/status`, `/now`. |
| `/help` | Lists the commands. |

There's no always-on listener — the scheduled run reads the bot's inbox at the
start of each cycle, so a reply lands **within 5 minutes**, not instantly.
Requested reports arrive with a notification; the daily heartbeat is silent.

Only messages from `TELEGRAM_CHAT_ID` are acted on. The bot's username is
public and strangers can message it; without that filter they could trigger
runs and read your watch status.

`state.json` holds `telegram_offset` so a message is only ever processed once.
That does mean a local run and the GitHub run compete for the inbox — whichever
polls first wins. In practice only Actions is running, so it doesn't come up.

## Usage

```bash
python -m bot.main               # normal check
python -m bot.main --dry-run     # scan and print; never send, never save
python -m bot.main --deep        # force the expensive checks this run
python -m bot.main --test-alert  # prove Telegram delivery works
```

Point it at a film that's already on sale to see a real alert render:

```bash
MOVIE_MATCH=odyssey RELEASE_DATE=2026-07-27 python -m bot.main --dry-run --deep
```

## Configuration

Everything in [`bot/config.py`](bot/config.py) is overridable by an environment
variable of the same name.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MOVIE_MATCH` | `doomsday` | Case-insensitive substring of the film title |
| `RELEASE_DATE` | `2026-12-17` | Date probed first each run (Event) |
| `WATCH_FROM` | `2026-11-01` | Re-probe any Event on-sale date at/after this |
| `CHAINS` | `event,hoyts` | Which providers run, and alert order |
| `DEEP_SWEEP_HOURS` | `6` | How often to force the expensive checks |
| `HEARTBEAT_HOURS` | `24` | "Still nothing" ping cadence; `0` disables |
| `MAX_SESSIONS_LISTED` | `6` | Sessions per cinema before "…and N more" |

Venue lists live next to each provider — `SYDNEY` in
[`bot/providers/event.py`](bot/providers/event.py) and
[`bot/providers/hoyts.py`](bot/providers/hoyts.py). Both also carry a `REGIONAL`
dict (Tuggerah, Shellharbour, Newcastle, Erina, Wollongong) if you'd travel.

Adding a chain is one file implementing `check(deep)` in
[`bot/providers/base.py`](bot/providers/base.py) terms, plus a line in
[`bot/providers/__init__.py`](bot/providers/__init__.py).

## State and noise control

`state.json` records which session keys you've already been told about, so you
get alerted once per newly-listed session rather than every 5 minutes forever.
The Actions job commits it back. It deliberately holds no run timestamp — that
would mean a commit every 5 minutes.

You also get a quiet daily heartbeat listing each chain's status, and an error
alert (at most every 12 hours) if a chain starts failing — which is what a site
change or an IP block would look like.

## Being genuinely early

The bot tells you within ~5 minutes of tickets appearing. To convert that:

- Have an **Event Cinebuzz** and a **HOYTS Rewards** account already created and
  logged in on your phone *and* desktop before December. Making an account at
  checkout is where the seat goes.
- Both chains run member presales ahead of general on-sale. This bot watches the
  *public* session lists, so a members-only presale that isn't publicly listed
  won't be seen — get on both mailing lists too.
- The two IMAX screens (Event Darling Harbour, HOYTS Blacktown) sell out first.
  They're first in the alert order for that reason.

## Known quirks

- **Event Bondi Junction** currently returns zero sessions on every date. It's
  left in the list and costs nothing; it'll report if the venue comes back.
- **Moonlight Cinema Sydney** is seasonal and returns no dates outside summer.
- These are unofficial endpoints. If a chain changes theirs, the error alert is
  your warning.
