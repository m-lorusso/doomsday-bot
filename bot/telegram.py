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
IMAX_COMMANDS = {"/imax"}
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


def send(text: str, token: str, chat_id: str, *, silent: bool = False) -> list:
    """Send `text` as HTML.

    Returns the ids of the messages sent, or an empty list if any part failed
    to deliver - so `if send(...)` still reads as "did it arrive".
    """
    if not token or not chat_id:
        print("[telegram not configured - message below]\n" + text)
        return []

    ids, ok = [], True
    for part in _chunks(text):
        try:
            reply = _api(token, "sendMessage", {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": silent,
            })
            ids.append((reply.get("result") or {}).get("message_id"))
        except urllib.error.HTTPError as exc:
            print(f"telegram error {exc.code}: {exc.read().decode('utf-8', 'replace')}")
            ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"telegram error: {exc}")
            ok = False
    return ids if ok else []


def pin(token: str, chat_id: str, message_id) -> bool:
    """Pin a message to the top of the chat. Bots may pin in private chats."""
    if not token or not chat_id or message_id is None:
        return False
    try:
        _api(token, "pinChatMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": False,
        })
        return True
    except Exception as exc:  # noqa: BLE001 - a failed pin must not lose the alert
        print(f"telegram pin failed: {exc}")
        return False


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
        "<b>/imax</b> — where IMAX stands right now\n"
        "<b>/check</b> — check every cinema now and report back\n"
        "<b>/help</b> — this message\n\n"
        "<i>Otherwise I stay quiet. The moment IMAX opens you get a loud alert, "
        "pinned to the top of this chat. Everything else is one quiet update a day.</i>"
    )
