"""Event Cinemas (includes IMAX Sydney).

Backed by the endpoint the session picker on eventcinemas.com.au calls:

    GET /Cinemas/GetSessions?cinemaIds=<id>&cinemaIds=<id>...&date=YYYY-MM-DD

Repeat `cinemaIds` to ask about several venues at once (a comma-separated list
returns a 500). One request for all sixteen Sydney venues returns exactly the
sessions sixteen separate requests would, in a fraction of the time - and
every request saved is one fewer chance to trip Cloudflare.

Two useful things come back:

  Movies - films with sessions *on the requested date*, each carrying
           CinemaModels[].Sessions[] with StartTime, ScreenTypeName,
           SeatsAvailable and a ready-to-use BookingUrl.
  Dates  - every date currently on sale at the requested venues. A film only
           appears on dates it actually plays, so finding one means probing
           the dates that matter.
"""

import time
import urllib.parse
from datetime import date

from .. import http
from ..dates import au_date
from .base import Provider, ProviderResult, Session

SITE = "https://www.eventcinemas.com.au"
BASE = SITE + "/Cinemas/GetSessions"
MOVIE_PAGE = SITE + "/movie/avengers-doomsday"
HEADERS = {"Referer": SITE + "/", "X-Requested-With": "XMLHttpRequest"}

IMAX_ID = 96
IMAX_LABEL = "IMAX Sydney"

# name -> id, from the site's own cinema picker. Order is alert order.
SYDNEY = {
    "IMAX Sydney": 96,
    "George Street": 15,
    "Bondi Junction": 64,
    "Parramatta": 66,
    "Castle Hill": 53,
    "Macquarie": 55,
    "Top Ryde City": 69,
    "Miranda": 82,
    "Hurstville": 7,
    "Burwood": 58,
    "Hornsby": 62,
    "Liverpool": 19,
    "Campbelltown": 65,
    "Ed Square": 94,
    "Drive In Blacktown": 5,
    "Moonlight Cinema Sydney": 75,
}
_NAME_BY_ID = {cid: name for name, cid in SYDNEY.items()}

# NSW but outside Greater Sydney - move into SYDNEY if you'd travel.
REGIONAL = {"Tuggerah": 9, "Shellharbour": 63, "Glendale": 21, "Kotara": 85, "Coffs Harbour": 36}

# Give up on a run's follow-up probes after this many failures in a row: that's
# a block, and backing off through every remaining date would take minutes.
GIVE_UP_AFTER = 2


def _ordinal(iso: str) -> int:
    return date.fromisoformat(iso[:10]).toordinal()


class EventProvider(Provider):
    name = "Event"

    def __init__(self, cfg):
        self.cfg = cfg
        self._warm = False
        # IMAX Sydney date -> when we last probed it. Lets the per-minute IMAX
        # check read each new date immediately but only a few old ones a tick.
        self._imax_probed: dict = {}

    # --- plumbing -----------------------------------------------------------

    def _get(self, cinema_ids, day: str) -> dict:
        if not self._warm:
            # Collect Cloudflare's cookie against the site root first, so the
            # first real request doesn't wear the challenge.
            http.warm_up(SITE + "/")
            self._warm = True
        query = urllib.parse.urlencode([("cinemaIds", c) for c in cinema_ids] + [("date", day)])
        try:
            payload = http.fetch_json(f"{BASE}?{query}", headers=HEADERS, retries=3, timeout=30)
        except http.FetchError:
            self._warm = False  # the cookie may have lapsed; re-warm next time
            raise
        if not payload.get("Success"):
            raise http.FetchError(f"Success=false for {day}")
        return payload.get("Data") or {}

    def _harvest(self, data: dict) -> list:
        needle = self.cfg.MOVIE_MATCH.lower()
        out = []
        for movie in data.get("Movies") or []:
            if needle not in (movie.get("Name") or "").lower():
                continue
            # Event flags member-only programming rather than hiding it, so a
            # Cinebuzz presale still comes down this same endpoint.
            members_only = bool(movie.get("ForCinebuzz"))
            for cm in movie.get("CinemaModels") or []:
                cid = cm.get("Id")
                cinema = _NAME_BY_ID.get(cid) or cm.get("Name") or "Event"
                for s in cm.get("Sessions") or []:
                    screen = s.get("ScreenTypeName") or s.get("ScreenType")
                    out.append(
                        Session(
                            chain=self.name,
                            cinema=cinema,
                            key=f"event:{s.get('Id')}",
                            start=s.get("StartTime"),
                            screen=screen,
                            seats=s.get("SeatsAvailable"),
                            booking_url=s.get("BookingUrl"),
                            members_only=members_only,
                            # IMAX Sydney only has the one screen; elsewhere,
                            # trust the session's own screen type.
                            imax=cid == IMAX_ID or "IMAX" in (screen or "").upper(),
                        )
                    )
        return out

    def _far_dates(self, dates, cap: int) -> list:
        """On-sale dates worth a follow-up probe, nearest the release first.

        Nearest-first matters: the calendar fills up day by day, and taking the
        *earliest* dates would spend the whole budget before reaching December.
        """
        release = self.cfg.RELEASE_DATE
        far = [d for d in dates if d >= self.cfg.WATCH_FROM and d[:10] != release]
        far.sort(key=lambda d: (abs(_ordinal(d) - _ordinal(release)), d))
        return far[:cap]

    # --- IMAX Sydney, every minute -------------------------------------------

    def check_imax(self) -> ProviderResult:
        res = ProviderResult(
            chain=self.name,
            venues=1,
            venue_order=[IMAX_LABEL],
            movie_url=MOVIE_PAGE,
            imax_label=IMAX_LABEL,
            imax_url=f"{MOVIE_PAGE}#cinemas={IMAX_ID}",
        )
        try:
            data = self._get([IMAX_ID], self.cfg.RELEASE_DATE)
        except http.FetchError as exc:
            res.imax_error = res.last_error = str(exc)
            return res
        res.checked = 1

        found = {s.key: s for s in self._harvest(data)}
        dates = data.get("Dates") or []
        far = self._far_dates(dates, cap=self.cfg.IMAX_MAX_DATES)
        # Dates we've never read go first, every tick. Then the few we read
        # longest ago, so sessions added to an already-open date still surface
        # within minutes without re-reading every date every minute.
        unread = [d for d in far if d not in self._imax_probed]
        read = sorted((d for d in far if d in self._imax_probed), key=self._imax_probed.get)
        for day in unread + read[: self.cfg.IMAX_REPROBE_PER_TICK]:
            time.sleep(self.cfg.REQUEST_DELAY_SECONDS)
            try:
                for s in self._harvest(self._get([IMAX_ID], day)):
                    found[s.key] = s
                self._imax_probed[day] = time.monotonic()
            except http.FetchError as exc:
                res.last_error = f"{IMAX_LABEL} {day}: {exc}"
                res.missed.append(au_date(day))

        res.sessions = [s for s in found.values() if s.imax]
        short = self.cfg.MOVIE_MATCH.title()
        if res.sessions:
            res.imax_status = f"ON SALE — {len(res.sessions)} IMAX sessions"
        elif dates:
            res.imax_status = f"no {short} sessions yet · booking open to {au_date(max(dates))}"
        else:
            res.imax_status = f"no {short} sessions yet · nothing on sale"
        return res

    # --- every Sydney venue --------------------------------------------------

    def check(self) -> ProviderResult:
        res = ProviderResult(
            chain=self.name, venues=len(SYDNEY), venue_order=list(SYDNEY), movie_url=MOVIE_PAGE
        )
        imax = self.check_imax()
        res.imax_label, res.imax_status = imax.imax_label, imax.imax_status
        res.imax_url, res.imax_error = imax.imax_url, imax.imax_error
        found = {s.key: s for s in imax.sessions}

        ids = list(SYDNEY.values())
        try:
            data = self._get(ids, self.cfg.RELEASE_DATE)
        except http.FetchError as exc:
            res.error = res.last_error = f"{au_date(self.cfg.RELEASE_DATE)}: {exc}"
            res.sessions = list(found.values())
            return res
        res.checked = len(SYDNEY)
        for s in self._harvest(data):
            found[s.key] = s

        dates = data.get("Dates") or []
        in_a_row = 0
        for day in self._far_dates(dates, cap=self.cfg.MAX_EXTRA_DATE_PROBES):
            time.sleep(self.cfg.REQUEST_DELAY_SECONDS)
            try:
                for s in self._harvest(self._get(ids, day)):
                    found[s.key] = s
                in_a_row = 0
            except http.FetchError as exc:
                res.last_error = f"{au_date(day)}: {exc}"
                res.missed.append(au_date(day))
                in_a_row += 1
                if in_a_row >= GIVE_UP_AFTER:
                    res.missed.append("later dates")
                    break

        res.sessions = list(found.values())
        if res.sessions:
            res.status = f"on sale — {len(res.sessions)} sessions"
        elif dates:
            res.status = f"listed, booking open only to {au_date(max(dates))}"
        else:
            res.status = "nothing on sale"
        return res
