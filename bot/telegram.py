"""Telegram delivery. Falls back to stdout when no token is configured, so you
can run and test the bot locally before setting anything up."""

import json
import urllib.error
import urllib.request

LIMIT = 3900  # Telegram caps a message at 4096 chars; leave headroom.


def _chunks(text: str):
    while len(text) > LIMIT:
        cut = text.rfind("\n", 0, LIMIT)
        if cut <= 0:
            cut = LIMIT
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def send(text: str, token: str, chat_id: str, *, silent: bool = False) -> bool:
    """Send `text` as HTML. Returns False if it couldn't be delivered."""
    if not token or not chat_id:
        print("[telegram not configured - message below]\n" + text)
        return False

    ok = True
    for part in _chunks(text):
        body = json.dumps(
            {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": silent,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            print(f"telegram error {exc.code}: {exc.read().decode('utf-8', 'replace')}")
            ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"telegram error: {exc}")
            ok = False
    return ok
