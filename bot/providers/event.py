"""Event Cinemas (includes IMAX Sydney).

Backed by the endpoint the session picker on eventcinemas.com.au calls:

    GET /Cinemas/GetSessions?cinemaIds=<id>&date=YYYY-MM-DD

Two useful things come back per cinema:

  Movies - films with sessions on the requested date, each carrying
           CinemaModels[].Sessions[] with StartTime, ScreenTypeName,
           SeatsAvailable and a ready-to-use BookingUrl.
  Dates  - the venue's *entire* on-sale calendar. Normally ~30 days out, so
           anything sitting in December is an advance-sale outlier worth a look.

Repeat the query param for multiple venues (cinemaIds=15&cinemaIds=64); a
comma-separated list returns a 500.
"""

import time
import urllib.parse

from .. import http
from ..dates import au_date
from .base import Provider, ProviderResult, Session

BASE = "https://www.eventcinemas.com.au/Cinemas/GetSessions"
MOVIE_PAGE = "https://www.eventcinemas.com.au/movie/avengers-doomsday"

# name -> id, from the site's own cinema picker.
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

# NSW but outside Greater Sydney - move into SYDNEY if you'd travel.
REGIONAL = {"Tuggerah": 9, "Shellharbour": 63, "Glendale": 21, "Kotara": 85, "Coffs Harbour": 36}


class EventProvider(Provider):
    name = "Event"

    def __init__(self, cfg):
        self.cfg = cfg

    def _get(self, cinema_id: int, date: str) -> dict:
        q = urllib.parse.urlencode({"cinemaIds": cinema_id, "date": date})
        payload = http.fetch_json(
            f"{BASE}?{q}",
            headers={"Referer": "https://www.eventcinemas.com.au/", "X-Requested-With": "XMLHttpRequest"},
        )
        if not payload.get("Success"):
            raise http.FetchError(f"Success=false for cinema {cinema_id} on {date}")
        return payload["Data"]

    def _harvest(self, data: dict, cinema: str) -> list:
        needle = self.cfg.MOVIE_MATCH.lower()
        out = []
        for movie in data.get("Movies") or []:
            if needle not in (movie.get("Name") or "").lower():
                continue
            # Event flags member-only programming rather than hiding it, so a
            # Cinebuzz presale still comes down this same endpoint. Worth
            # calling out in the alert: you'll need a membership to book it.
            members_only = bool(movie.get("ForCinebuzz"))
            for cm in movie.get("CinemaModels") or []:
                for s in cm.get("Sessions") or []:
                    out.append(
                        Session(
                            chain=self.name,
                            cinema=cm.get("Name") or cinema,
                            key=f"event:{s.get('Id')}",
                            start=s.get("StartTime"),
                            screen=s.get("ScreenTypeName") or s.get("ScreenType"),
                            seats=s.get("SeatsAvailable"),
                            booking_url=s.get("BookingUrl"),
                            members_only=members_only,
                        )
                    )
        return out

    def check(self, deep: bool = False) -> ProviderResult:
        res = ProviderResult(
            chain=self.name, venues=len(SYDNEY), venue_order=list(SYDNEY), movie_url=MOVIE_PAGE
        )
        horizons = []

        # Collect Cloudflare's cookies against the site root first. Without
        # this the first venue wears the challenge and 403s on its own, which
        # is why IMAX Sydney - simply for being first in the list - was the
        # only venue that ever failed.
        http.warm_up("https://www.eventcinemas.com.au/")

        for cinema, cid in SYDNEY.items():
            try:
                data = self._get(cid, self.cfg.RELEASE_DATE)
            except http.FetchError as exc:
                res.failed_venues.append(cinema)
                res.last_error = f"{cinema}: {exc}"
                continue

            dates = data.get("Dates") or []
            if dates:
                horizons.append(dates[-1])
            res.sessions.extend(self._harvest(data, cinema))

            # Anything on sale unusually far out gets a second look - that's
            # what an advance-sale drop looks like before our guessed release
            # date happens to match exactly.
            extra = [d for d in dates if d >= self.cfg.WATCH_FROM and d != self.cfg.RELEASE_DATE]
            for date in extra[: self.cfg.MAX_EXTRA_DATE_PROBES]:
                time.sleep(self.cfg.REQUEST_DELAY_SECONDS)
                try:
                    res.sessions.extend(self._harvest(self._get(cid, date), cinema))
                except http.FetchError as exc:
                    # A missed follow-up date isn't a missed venue: the venue
                    # itself answered, so don't mark it down for this.
                    res.last_error = f"{cinema} {date}: {exc}"

            time.sleep(self.cfg.REQUEST_DELAY_SECONDS)

        if res.sessions:
            res.status = f"ON SALE — {len(res.sessions)} sessions"
        elif horizons:
            res.status = f"listed, booking open only to {au_date(max(horizons))}"
        res.checked = len(SYDNEY) - len(res.failed_venues)
        # Only a wholesale failure is an error worth shouting about. One venue
        # out of sixteen glitching is noise, and treating it as an outage
        # trains you to ignore the alert that matters.
        if not res.checked:
            res.error = res.last_error or "every venue failed"
        return res
