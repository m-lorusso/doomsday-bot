"""One tiny HTTP helper so every provider retries and identifies itself the
same way. Standard library only - nothing to pip install."""

import gzip
import json
import time
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class FetchError(RuntimeError):
    pass


def fetch(url: str, *, headers: dict | None = None, retries: int = 3, timeout: int = 60) -> bytes:
    hdr = {
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
        "Accept-Encoding": "gzip",
    }
    hdr.update(headers or {})

    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise FetchError(f"{url}: {last}") from last


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw).decode("utf-8"))


def fetch_text(url: str, **kw) -> str:
    return fetch(url, **kw).decode("utf-8", "replace")
