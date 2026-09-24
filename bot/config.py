"""Everything you'd want to tweak lives here, and every value can be overridden
by an environment variable of the same name."""

import os


def _env(name, default):
    return os.environ.get(name, default)


# --- What we're hunting -----------------------------------------------------

# Matched case-insensitively against the film title each chain reports. Kept
# deliberately loose so a chain writing "Avengers Doomsday" without the colon,
# or appending "(IMAX)", still matches.
MOVIE_MATCH = _env("MOVIE_MATCH", "doomsday")

# What the notifications call it. Separate from MOVIE_MATCH, which is a
# substring and reads badly as a headline.
MOVIE_TITLE = _env("MOVIE_TITLE", "Avengers: Doomsday")

# AU release date. Event is probed against this date directly.
RELEASE_DATE = _env("RELEASE_DATE", "2026-12-17")

# Event dates from here on get a follow-up probe. Doomsday's sessions start
# with the 16 Dec previews; a couple of days' margin covers fan events.
WATCH_FROM = _env("WATCH_FROM", "2026-12-14")

# --- Who we watch -----------------------------------------------------------

# Order matters: it's the order cinemas appear in the alert.
CHAINS = [c.strip() for c in _env("CHAINS", "event,hoyts").split(",") if c.strip()]

# --- Telegram ---------------------------------------------------------------

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")

# A quiet status report at most this often, so silence never means "it broke
# three weeks ago and nobody noticed". 0 disables it.
HEARTBEAT_HOURS = int(_env("HEARTBEAT_HOURS", "24"))

# --- IMAX -------------------------------------------------------------------

# How often the watch loop (--imax-watch) looks at the two IMAX screens.
IMAX_POLL_SECONDS = int(_env("IMAX_POLL_SECONDS", "60"))

# During the watch loop, a full check of every venue this often.
FULL_CHECK_MINUTES = int(_env("FULL_CHECK_MINUTES", "15"))

# IMAX Sydney dates worth reading, and how many already-read dates to re-read
# each tick so sessions added to an open date still surface quickly.
IMAX_MAX_DATES = int(_env("IMAX_MAX_DATES", "30"))
IMAX_REPROBE_PER_TICK = int(_env("IMAX_REPROBE_PER_TICK", "3"))

# Sessions listed per IMAX venue in the alert. Higher than the general alert:
# for IMAX you want to see the whole of opening night before you tap.
IMAX_SESSIONS_LISTED = int(_env("IMAX_SESSIONS_LISTED", "12"))

# Tell you if IMAX checks have been failing for this long.
IMAX_FAIL_ALERT_MINUTES = int(_env("IMAX_FAIL_ALERT_MINUTES", "30"))

# --- Plumbing ---------------------------------------------------------------

STATE_FILE = _env("STATE_FILE", "state.json")
LOG_FILE = _env("LOG_FILE", "")  # append output here instead of the console
REQUEST_DELAY_SECONDS = float(_env("REQUEST_DELAY_SECONDS", "0.5"))

# Event dates probed per full check, nearest the release first. Each probe is
# one request covering all sixteen venues.
MAX_EXTRA_DATE_PROBES = int(_env("MAX_EXTRA_DATE_PROBES", "21"))

# On opening weekend one cinema can have 30+ sessions. Listing every one turns
# the alert into a wall of text split over several Telegram messages, which is
# the opposite of useful when you're trying to move fast.
MAX_SESSIONS_LISTED = int(_env("MAX_SESSIONS_LISTED", "6"))

# Same reasoning for venues: best screens lead, the rest are one tap away.
MAX_CINEMAS_LISTED = int(_env("MAX_CINEMAS_LISTED", "8"))

# Minimum gap between "a chain is failing" alerts.
ERROR_ALERT_HOURS = float(_env("ERROR_ALERT_HOURS", "12"))
