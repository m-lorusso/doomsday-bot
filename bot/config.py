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

# Advertised AU release date. Event is probed against this date directly.
RELEASE_DATE = _env("RELEASE_DATE", "2026-12-17")

# If the release slips, or previews open a day early, we still catch it: any
# Event on-sale date from here onwards gets a second look.
WATCH_FROM = _env("WATCH_FROM", "2026-11-01")

# --- Who we watch -----------------------------------------------------------

# Order matters: it's the order cinemas appear in the alert.
CHAINS = [c.strip() for c in _env("CHAINS", "event,hoyts").split(",") if c.strip()]

# --- Telegram ---------------------------------------------------------------

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")

# A quiet "checked, still nothing" message at most this often, so silence never
# means "it broke three weeks ago and nobody noticed". 0 disables it.
HEARTBEAT_HOURS = int(_env("HEARTBEAT_HOURS", "24"))

# --- Plumbing ---------------------------------------------------------------

STATE_FILE = _env("STATE_FILE", "state.json")
REQUEST_DELAY_SECONDS = float(_env("REQUEST_DELAY_SECONDS", "0.7"))

# Safety valve on Event's follow-up date probes (per cinema, per run).
MAX_EXTRA_DATE_PROBES = int(_env("MAX_EXTRA_DATE_PROBES", "12"))

# On opening weekend one cinema can have 30+ sessions. Listing every one turns
# the alert into a wall of text split over several Telegram messages, which is
# the opposite of useful when you're trying to move fast.
MAX_SESSIONS_LISTED = int(_env("MAX_SESSIONS_LISTED", "6"))

# Same reasoning for venues: 28 cinemas x several sessions each would span half
# a dozen Telegram messages. Best screens lead, the rest are one tap away.
MAX_CINEMAS_LISTED = int(_env("MAX_CINEMAS_LISTED", "8"))

# HOYTS' cheap `onSale` flag drives most runs; occasionally we pull the full
# 4.8 MB session dump anyway in case that flag lags behind the real listings.
DEEP_SWEEP_HOURS = float(_env("DEEP_SWEEP_HOURS", "6"))
