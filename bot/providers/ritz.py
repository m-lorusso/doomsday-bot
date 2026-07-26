"""The Ritz, Randwick.

Single-venue site running the same platform as HOYTS, so `/api/movies` has the
same shape - including the `onSale` boolean. There's no `/api/sessions` here,
so the flag flipping is the whole signal: we can tell you it's bookable, just
not which times.
"""

from .. import http
from .base import Provider, ProviderResult, Session

SITE = "https://www.ritzcinemas.com.au"


class RitzProvider(Provider):
    name = "Ritz Randwick"

    def __init__(self, cfg):
        self.cfg = cfg

    def check(self, deep: bool = False) -> ProviderResult:
        res = ProviderResult(chain=self.name)
        needle = self.cfg.MOVIE_MATCH.lower()

        try:
            movies = http.fetch_json(SITE + "/api/movies", headers={"Referer": SITE + "/"})
        except http.FetchError as exc:
            res.error = str(exc)
            return res

        matches = [m for m in movies if needle in (m.get("name") or "").lower()]
        if not matches:
            res.status = f"'{self.cfg.MOVIE_MATCH}' not listed"
            return res

        for m in matches:
            if not m.get("onSale"):
                continue
            link = m.get("link") or "/movies"
            res.sessions.append(
                Session(
                    chain=self.name,
                    cinema="Ritz Randwick",
                    key=f"ritz:onsale:{m.get('id')}",
                    booking_url=SITE + link,
                    note="tickets on sale - times on the site",
                )
            )

        res.status = "ON SALE" if res.sessions else "listed, onSale=false"
        return res
