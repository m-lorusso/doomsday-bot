"""Telegram delivery, plus a light inbox poll so the bot can answer commands.

Sending falls back to stdout when no token is configured, so you can run and
test the whole thing locally before setting anything up.
"""

import json
import urllib.error
import urllib.request

LIMIT = 3900  # Telegram caps a message at 4096 chars; leave headroom.

# Commands we understand, lowercase, without the @botname suffix Telegram adds
# in group chats.
CHECK_COMMANDS = {"/check", "/status", "/now"}
HELP_COMMANDS = {"/help", "/start"}


def _api(token: str, method: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
        try:
            _api(token, "sendMessage", {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": silent,
            })
        except urllib.error.HTTPError as exc:
            print(f"telegram error {exc.code}: {exc.read().decode('utf-8', 'replace')}")
            ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"telegram error: {exc}")
            ok = False
    return ok


def poll_commands(token: str, chat_id: str, offset: int | None) -> tuple:
    """Read anything sent to the bot since `offset`.

    Returns (commands, next_offset). `commands` is the set of recognised
    commands seen; next_offset is what to pass in next time.

    Messages from anyone other than `chat_id` are ignored outright. The bot's
    username is public, so strangers can and will message it - without this
    filter they could trigger runs and read back your watch status.
    """
    if not token or not chat_id:
        return set(), offset

    payload = {"timeout": 0, "allowed_updates": ["message"]}
    if offset is not None:
        # Acknowledges everything below this id, so we never reprocess.
        payload["offset"] = offset

    try:
        data = _api(token, "getUpdates", payload)
    except Exception as exc:  # noqa: BLE001 - never let the inbox break a check
        print(f"telegram getUpdates failed: {exc}")
        return set(), offset

    seen, next_offset = set(), offset
    for update in data.get("result") or []:
        next_offset = max(next_offset or 0, update.get("update_id", 0) + 1)
        message = update.get("message") or {}
        if str((message.get("chat") or {}).get("id")) != str(chat_id):
            continue
        # "/check@DoomsdayBot" -> "/check"
        word = (message.get("text") or "").strip().split()[:1]
        if word:
            seen.add(word[0].split("@")[0].lower())
    return seen, next_offset


def help_text(title: str) -> str:
    return (
        f"\U0001f916 <b>{title} watch</b>\n\n"
        "<b>/check</b> — run a check now and report back\n"
        "<b>/help</b> — this message\n\n"
        "<i>Otherwise I stay quiet: I check every 5 minutes on my own and only "
        "message you the moment tickets go on sale, plus one status update a day.</i>"
    )
