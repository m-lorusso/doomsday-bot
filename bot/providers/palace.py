"""Palace Cinemas - Central, Norton Street, Moore Park, Chauvel, Verona.

A Next.js site, so the page ships its own data in the `__NEXT_DATA__` script
tag. `props.pageProps.sessions` on a film's page is `[]` until that film is
bookable, which is a cleaner signal than scraping rendered markup.

One request covers every Palace venue at once.
"""

import json
import re

from .. import http
from .base import Provider, ProviderResult, Session

SITE = "https://www.palacecinemas.com.au"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

SYDNEY_CINEMA_IDS = {"129": "Palace Norton Street", "200": "Palace Central", "210": "Palace Moore Park"}


class PalaceProvider(Provider):
    name = "Palace"

    def __init__(self, cfg):
        self.cfg = cfg
        self.slug = cfg.PALACE_SLUG

    def check(self, deep: bool = False) -> ProviderResult:
        res = ProviderResult(chain=self.name)
        url = f"{SITE}/movies/{self.slug}"

        try:
            html = http.fetch_text(url, headers={"Referer": SITE + "/"})
        except http.FetchError as exc:
            res.error = str(exc)
            return res

        m = NEXT_DATA.search(html)
        if not m:
            res.error = "no __NEXT_DATA__ on the page (site layout changed?)"
            return res

        try:
            props = json.loads(m.group(1))["props"]["pageProps"]
        except (KeyError, json.JSONDecodeError) as exc:
            res.error = f"unexpected page payload: {exc}"
            return res

        if not props.get("movie"):
            res.status = f"/movies/{self.slug} has no film (slug changed?)"
            return res

        sessions = props.get("sessions") or []
        if not sessions:
            res.status = "listed, no sessions yet"
            return res

        # Shape varies by film; pull what's there and fall back to a page-level
        # alert rather than guessing at a schema that might not hold.
        for entry in sessions:
            if not isinstance(entry, dict):
                continue
            res.sessions.append(
                Session(
                    chain=self.name,
                    cinema=SYDNEY_CINEMA_IDS.get(str(entry.get("cinemaId")), "Palace (see site)"),
                    key=f"palace:{entry.get('sessionId') or entry.get('movieId') or self.slug}",
                    start=entry.get("sessionTime") or entry.get("startTime"),
                    booking_url=entry.get("bookingUrl") or url,
                    note="sessions listed on the Palace site",
                )
            )

        res.status = f"{len(res.sessions)} session entries"
        return res
