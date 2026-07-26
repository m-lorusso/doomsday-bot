"""HOYTS (includes IMAX Blacktown).

Open, unauthenticated JSON API:

    GET .../api/movies    ~195 KB  every film, each with an `onSale` boolean
                                   and a `vistaId` (sometimes comma-separated)
    GET .../api/sessions  ~4.8 MB  every session at every HOYTS in Australia
    GET .../api/cinemas   ~28 KB   venue list with state/suburb

/sessions ignores query parameters - it's all-or-nothing, hence the two-stage
approach: poll the cheap /movies flag every run, and only pull the big session
dump when that flag flips (or on an occasional deep sweep, in case the flag
lags behind reality).
"""

from .. import http
from .base import Provider, ProviderResult, Session

BASE = "https://apim-aea.hoyts.com.au/cinemaapi-au-live/api/"
SITE = "https://www.hoyts.com.au"

# HOYTS venue id -> display name. Greater Sydney only; the API's `state` field
# is NSW for Newcastle/Central Coast/Wollongong too, so this is hand-picked.
SYDNEY = {
    "WESCIN": "Blacktown (IMAX)",
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

# typeId comes through SHOUTING; .title() would give "Imax", which reads wrong
# for exactly the screens you most want to spot.
SCREEN_NAMES = {
    "IMAX": "IMAX",
    "SCREENX": "ScreenX",
    "XTREME": "Xtremescreen",
    "DBOX": "D-BOX",
    "LUX": "LUX",
    "STANDARD": "Standard",
}


def _screen(type_id: str | None) -> str | None:
    if not type_id:
        return None
    return SCREEN_NAMES.get(type_id.upper(), type_id.title())


class HoytsProvider(Provider):
    name = "HOYTS"

    def __init__(self, cfg):
        self.cfg = cfg

    def check(self, deep: bool = False) -> ProviderResult:
        res = ProviderResult(
            chain=self.name,
            venues=len(SYDNEY),
            venue_order=list(SYDNEY.values()),
            movie_url=SITE + "/movies/avengers-doomsday",
        )
        needle = self.cfg.MOVIE_MATCH.lower()

        try:
            movies = http.fetch_json(BASE + "movies", headers={"Referer": SITE + "/"})
        except http.FetchError as exc:
            res.error = f"movies: {exc}"
            return res

        matches = [m for m in movies if needle in (m.get("name") or "").lower()]
        if not matches:
            res.status = "film not listed on the site yet"
            return res

        # The site links the film's page from its own listing, so follow that
        # rather than assuming the slug.
        link = (matches[0].get("link") or "").strip()
        if link.startswith("/"):
            res.movie_url = SITE + link

        on_sale = [m for m in matches if m.get("onSale")]
        res.status = "ON SALE" if on_sale else "listed, tickets not released"

        # The cheap flag says no and we're not doing a deep sweep - stop here
        # rather than pulling 4.8 MB.
        if not on_sale and not deep:
            return res

        try:
            sessions = http.fetch_json(BASE + "sessions", headers={"Referer": SITE + "/"})
        except http.FetchError as exc:
            res.error = f"sessions: {exc}"
            return res

        # vistaId can be "HO00008129,HO00011223" - one film, several Vista codes.
        wanted = {v.strip() for m in matches for v in (m.get("vistaId") or "").split(",") if v.strip()}

        for s in sessions:
            if s.get("movieId") not in wanted or s.get("disabled"):
                continue
            cid = s.get("cinemaId")
            if cid not in SYDNEY:
                continue
            link = s.get("link") or ""
            res.sessions.append(
                Session(
                    chain=self.name,
                    cinema=SYDNEY[cid],
                    key=f"hoyts:{s.get('id')}",
                    start=s.get("date"),
                    screen=_screen(s.get("typeId")),
                    booking_url=(SITE + link) if link.startswith("/") else (link or None),
                )
            )

        if res.sessions:
            res.status = f"ON SALE — {len(res.sessions)} sessions"
        return res
