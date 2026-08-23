"""One tiny HTTP helper so every provider retries and identifies itself the
same way. Standard library only - nothing to pip install.

Event sits behind Cloudflare, which intermittently 403s a cold request from a
datacentre IP - which is exactly what a GitHub Actions runner is. Two things
keep that from turning into a failed check:

  * a shared cookie jar, so the clearance cookie handed out on the first
    request is reused by every request after it, and
  * `warm_up()`, which fetches the site root before the API calls so that
    first challenge lands somewhere harmless.

A 403 also gets longer, more patient backoff than an ordinary blip, because
Cloudflare's hold lasts a good deal longer than the one second an immediate
retry would wait.
"""

import gzip
import http.cookiejar
import json
import time
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# One jar for the whole run: cookies picked up warming up are then sent with
# the API calls that follow.
_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_JAR))

# Waits after a 403, in seconds. Deliberately slower than the generic retry:
# a Cloudflare block that clears at all takes several seconds to do it.
BLOCKED_BACKOFF = (4, 12, 30)


class FetchError(RuntimeError):
    pass


def _backoff(exc: Exception, attempt: int) -> float:
    blocked = isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 429, 503)
    if blocked:
        return BLOCKED_BACKOFF[min(attempt, len(BLOCKED_BACKOFF) - 1)]
    return 2**attempt


def fetch(url: str, *, headers: dict | None = None, retries: int = 4, timeout: int = 60) -> bytes:
    hdr = {
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Connection": "keep-alive",
    }
    hdr.update(headers or {})

    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with _OPENER.open(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last = exc
            if attempt < retries - 1:
                time.sleep(_backoff(exc, attempt))
    raise FetchError(f"{url}: {last}") from last


def warm_up(url: str) -> bool:
    """Fetch a page to collect cookies before the real requests.

    Never raises: failing to warm up isn't itself a problem, it just means the
    first real request wears whatever challenge was coming anyway.
    """
    try:
        fetch(url, headers={"Accept": "text/html,application/xhtml+xml"}, retries=2, timeout=30)
        return True
    except FetchError:
        return False


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw).decode("utf-8"))


def fetch_text(url: str, **kw) -> str:
    return fetch(url, **kw).decode("utf-8", "replace")
