"""HOYTS (includes IMAX at Blacktown).

Open, unauthenticated JSON API:

    GET .../api/movies            ~195 KB  every film: name, `onSale`, and its
                                           Vista film codes in `vistaId`
                                           (comma-separated when a film has
                                           several versions)
    GET .../api/sessions/<venue>  ~150 KB  every session at one venue, all dates

Sessions carry `typeId` (IMAX, STANDARD, XTREME, ...) and `screenName`
("IMAX 01"), so an IMAX session is identifiable on its own - no guessing from
the venue.

There's also a national `/api/sessions` (4.8 MB). The per-venue route makes it
unnecessary: twelve small reads cost less than one big one, and reading
sessions directly means we no longer lean on the `onSale` flag, which on the
day Doomsday opened lagged the actual listings by hours.
"""

import time

from .. import http
from ..dates import au_date
from .base import Provider, ProviderResult, Session

BASE = "https://apim-aea.hoyts.com.au/cinemaapi-au-live/api/"
SITE = "https://www.hoyts.com.au"
HEADERS = {"Referer": SITE + "/"}

# HOYTS venue id -> display name. Greater Sydney only; the API's `state` field
# is NSW for Newcastle/Central Coast/Wollongong too, so this is hand-picked.
# Order is alert order.
SYDNEY = {
    "WESCIN": "Blacktown",
    "BROADW": "Broadway",
    "SHOWGR": "Entertainment Quarter",
    "CWFFLD": "Chatswood Westfield",
    "CHWOOD": "Chatswood Mandarin",
    "EGDENS": "Eastgardens",
    "WGHMAL": "Warringah Mall",
    "BANKTN": "Bankstown",
    "CROCIN": "Cronulla",
    "MTDRTT": "Mt Druitt",
    "PENRTH": "Penrith",
    "WETHER": "Wetherill Park",
}

# NSW, outside Greater Sydney.
REGIONAL = {"ERINAF": "Erina", "CHARLE": "Charlestown", "GHLCIN": "Green Hills", "WWGCIN": "Warrawong"}

IMAX_VENUE = "WESCIN"
IMAX_LABEL = "Blacktown IMAX"

# typeId comes through SHOUTING; .title() would give "Imax", which reads wrong
# for exactly the screens you most want to spot.
SCREEN_NAMES = {
    "IMAX": "IMAX",
    "SCREENX": "ScreenX",
    "XTREME": "Xtremescreen",
    "DBOX": "D-BOX",
    "LUX": "LUX",
    "APEX": "APEX",
    "LOUNGES": "Lounges",
    "STANDARD": "Standard",
}

GIVE_UP_AFTER = 3  # venue failures in a row before we call it a block
TITLES_MAX_AGE = 30 * 60  # refresh the film list at least this often (seconds)
TITLES_MIN_GAP = 5 * 60  # ...but never more often than this on demand


def _screen(type_id: str | None) -> str | None:
    if not type_id:
        return None
    return SCREEN_NAMES.get(type_id.upper(), type_id.title())


def _is_imax(row: dict) -> bool:
    return "IMAX" in (row.get("typeId") or "").upper() or "IMAX" in (row.get("screenName") or "").upper()


class HoytsProvider(Provider):
    name = "HOYTS"

    def __init__(self, cfg):
        self.cfg = cfg
        self._titles: dict = {}  # Vista film code -> film name
        self._matches: list = []  # /movies entries whose name matches
        self._titles_at = 0.0

    # --- plumbing -----------------------------------------------------------

    def _refresh_titles(self, *, force: bool = False) -> None:
        age = time.monotonic() - self._titles_at
        if self._titles and age < (TITLES_MIN_GAP if force else TITLES_MAX_AGE):
            return
        movies = http.fetch_json(BASE + "movies", headers=HEADERS, retries=3, timeout=30)
        needle = self.cfg.MOVIE_MATCH.lower()
        titles = {}
        for m in movies:
            for code in (m.get("vistaId") or "").split(","):
                if code.strip():
                    titles[code.strip()] = m.get("name") or ""
        self._titles = titles
        self._matches = [m for m in movies if needle in (m.get("name") or "").lower()]
        self._titles_at = time.monotonic()

    def _wanted(self) -> set:
        # Matching by *name* rather than a fixed code list means a new version -
        # an IMAX print, say - is picked up even if it arrives under a film code
        # we've never seen before.
        needle = self.cfg.MOVIE_MATCH.lower()
        return {code for code, name in self._titles.items() if needle in name.lower()}

    def _venue(self, venue_id: str) -> list:
        return http.fetch_json(BASE + f"sessions/{venue_id}", headers=HEADERS, retries=3, timeout=30)

    def _session(self, row: dict, cinema: str) -> Session:
        link = row.get("link") or ""
        return Session(
            chain=self.name,
            cinema=cinema,
            key=f"hoyts:{row.get('id')}",
            start=row.get("date"),
            screen=_screen(row.get("typeId")),
            booking_url=(SITE + link) if link.startswith("/") else (link or None),
            imax=_is_imax(row),
        )

    def _movie_url(self) -> str:
        link = (self._matches[0].get("link") or "").strip() if self._matches else ""
        return SITE + link if link.startswith("/") else SITE + "/movies/avengers-doomsday"

    def _imax_summary(self, res: ProviderResult, rows: list) -> list:
        """Fill in the IMAX fields from Blacktown's session list; return our IMAX sessions."""
        imax_rows = [r for r in rows if _is_imax(r) and not r.get("disabled")]
        # A film code we've never seen on the IMAX screen could be the IMAX
        # version of ours. Worth one extra read of the film list to find out.
        if any(r.get("movieId") not in self._titles for r in imax_rows):
            try:
                self._refresh_titles(force=True)
            except http.FetchError:
                pass
        wanted = self._wanted()
        found = [self._session(r, SYDNEY[IMAX_VENUE]) for r in imax_rows if r.get("movieId") in wanted]

        res.imax_label = IMAX_LABEL
        res.imax_url = self._movie_url()
        short = self.cfg.MOVIE_MATCH.title()
        booked_to = max((r.get("date") or "" for r in imax_rows), default="")
        if found:
            res.imax_status = f"ON SALE — {len(found)} IMAX sessions"
        elif booked_to:
            res.imax_status = f"no {short} sessions yet · IMAX screen booked to {au_date(booked_to)}"
        else:
            res.imax_status = f"no {short} sessions yet · IMAX screen has nothing on sale"
        return found

    # --- Blacktown IMAX, every minute ---------------------------------------

    def check_imax(self) -> ProviderResult:
        res = ProviderResult(
            chain=self.name, venues=1, venue_order=[SYDNEY[IMAX_VENUE]], imax_label=IMAX_LABEL
        )
        try:
            self._refresh_titles()
            rows = self._venue(IMAX_VENUE)
        except http.FetchError as exc:
            res.imax_error = res.last_error = str(exc)
            return res
        res.checked = 1
        res.movie_url = self._movie_url()
        res.sessions = self._imax_summary(res, rows)
        return res

    # --- every Sydney venue --------------------------------------------------

    def check(self) -> ProviderResult:
        res = ProviderResult(
            chain=self.name,
            venues=len(SYDNEY),
            venue_order=list(SYDNEY.values()),
            imax_label=IMAX_LABEL,
        )
        try:
            self._refresh_titles(force=True)
        except http.FetchError as exc:
            res.error = res.last_error = res.imax_error = f"film list: {exc}"
            return res
        res.movie_url = self._movie_url()
        wanted = self._wanted()

        found: dict = {}
        in_a_row = 0
        for venue_id, cinema in SYDNEY.items():
            try:
                rows = self._venue(venue_id)
            except http.FetchError as exc:
                res.missed.append(cinema)
                res.last_error = f"{cinema}: {exc}"
                if venue_id == IMAX_VENUE:
                    res.imax_error = res.last_error
                in_a_row += 1
                if in_a_row >= GIVE_UP_AFTER and not res.checked:
                    res.missed.extend(c for c in SYDNEY.values() if c not in res.missed)
                    break
                continue
            in_a_row = 0
            res.checked += 1
            if venue_id == IMAX_VENUE:
                self._imax_summary(res, rows)
            for row in rows:
                if row.get("movieId") in wanted and not row.get("disabled"):
                    s = self._session(row, cinema)
                    found[s.key] = s
            time.sleep(0.2)

        if not res.checked:
            res.error = res.last_error or "every venue failed"
        res.sessions = list(found.values())
        if res.sessions:
            res.status = f"on sale — {len(res.sessions)} sessions"
        elif self._matches and not any(m.get("onSale") for m in self._matches):
            res.status = "listed, tickets not released"
        elif self._matches:
            res.status = "listed, no Sydney sessions yet"
        else:
            res.status = "film not listed on the site yet"
        return res
