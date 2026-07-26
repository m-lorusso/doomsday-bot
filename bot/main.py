"""Check whether the target movie has gone on sale at any watched Sydney
cinema, and shout on Telegram the moment it has.

    python -m bot.main                normal check
    python -m bot.main --dry-run      scan and print; never send, never save
    python -m bot.main --test-alert   prove Telegram delivery works
    python -m bot.main --deep         force the expensive checks this run
"""

import argparse
import html
import json
import sys
from datetime import datetime, timedelta, timezone

from . import config, providers, telegram

SYD = timezone(timedelta(hours=11))  # AEDT, for display only


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --- state ------------------------------------------------------------------


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _cooldown_passed(iso: str, hours: float) -> bool:
    if not iso:
        return True
    try:
        last = datetime.fromisoformat(iso)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now_utc() - last >= timedelta(hours=hours)


# --- messages ---------------------------------------------------------------


def fmt_session(s) -> str:
    bits = []
    if s.start:
        when = s.start
        try:
            when = datetime.fromisoformat(s.start).strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
        except ValueError:
            pass
        bits.append(f"<b>{html.escape(when)}</b>")
    if s.screen:
        bits.append(html.escape(s.screen))
    if isinstance(s.seats, int):
        bits.append(f"{s.seats} seats")
    if not bits and s.note:
        bits.append(html.escape(s.note))
    line = "  - " + " ".join(bits) if bits else "  - bookable"
    if s.booking_url:
        line += f' <a href="{html.escape(s.booking_url, quote=True)}">book</a>'
    return line


def build_alert(results: list, new_keys: set) -> str:
    lines = [f"\U0001f6a8 <b>{html.escape(config.MOVIE_MATCH.title())} IS ON SALE</b>", ""]
    for r in results:
        fresh = [s for s in r.sessions if s.key in new_keys]
        if not fresh:
            continue
        lines.append(f"— <b>{html.escape(r.chain)}</b> —")
        by_cinema = {}
        for s in fresh:
            by_cinema.setdefault(s.cinema, []).append(s)
        for cinema, group in by_cinema.items():
            group.sort(key=lambda s: s.start or "")
            shown = group[: config.MAX_SESSIONS_LISTED]
            lines.append(f"<b>{html.escape(cinema)}</b> ({len(group)})")
            lines.extend(fmt_session(s) for s in shown)
            if len(group) > len(shown):
                lines.append(f"  ...and {len(group) - len(shown)} more")
        lines.append("")
    return "\n".join(lines).strip()


def build_heartbeat(results: list) -> str:
    stamp = now_utc().astimezone(SYD).strftime("%d %b %H:%M")
    lines = [
        f"✅ Checked {len(results)} chains at {stamp} AEDT — "
        f"{html.escape(config.MOVIE_MATCH.title())} not on sale yet.",
        "",
    ]
    for r in results:
        state = r.error and f"⚠️ {r.error[:90]}" or (r.status or "no signal")
        lines.append(f"• <b>{html.escape(r.chain)}</b>: {html.escape(state)}")
    return "\n".join(lines)


# --- entry point ------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watch Sydney cinemas for a movie going on sale.")
    ap.add_argument("--dry-run", action="store_true", help="scan but never send or save")
    ap.add_argument("--test-alert", action="store_true", help="send a test message and exit")
    ap.add_argument("--deep", action="store_true", help="force the expensive checks this run")
    ap.add_argument("--force-heartbeat", action="store_true", help="ignore the heartbeat cooldown")
    args = ap.parse_args(argv)

    token, chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID

    if args.test_alert:
        ok = telegram.send("\U0001f9ea Doomsday bot test — notifications are working.", token, chat)
        print("sent" if ok else "not delivered")
        return 0 if ok else 1

    state = load_state(config.STATE_FILE)
    alerted = set(state.get("alerted_keys", []))
    deep = args.deep or _cooldown_passed(state.get("last_deep_sweep", ""), config.DEEP_SWEEP_HOURS)

    print(f"Checking {', '.join(config.CHAINS)} for '{config.MOVIE_MATCH}' (deep={deep})")
    results = []
    for provider in providers.build(config):
        try:
            r = provider.check(deep=deep)
        except Exception as exc:  # noqa: BLE001 - one bad chain shouldn't kill the run
            r = providers.ProviderResult(chain=provider.name, error=f"unhandled: {exc}")
        results.append(r)
        print(
            f"  {r.chain:<14} sessions={len(r.sessions):<4} {r.status or ''}"
            + (f"  ERROR={r.error}" if r.error else "")
        )

    found = {s.key for r in results for s in r.sessions}
    new_keys = found - alerted
    errored = [r for r in results if r.error]

    if new_keys:
        body = build_alert(results, new_keys)
        print("\n" + body)
        if args.dry_run:
            print("\n(dry run — not sent, state not advanced)")
        elif telegram.send(body, token, chat):
            alerted |= new_keys
    else:
        print("\nNot on sale yet.")
        if not args.dry_run and (
            args.force_heartbeat
            or (config.HEARTBEAT_HOURS > 0 and _cooldown_passed(state.get("last_heartbeat", ""), config.HEARTBEAT_HOURS))
        ):
            if telegram.send(build_heartbeat(results), token, chat, silent=True):
                state["last_heartbeat"] = now_utc().isoformat()

    if errored and not args.dry_run and _cooldown_passed(state.get("last_error_alert", ""), 12):
        names = ", ".join(r.chain for r in errored)
        if telegram.send(
            f"⚠️ Doomsday bot: {html.escape(names)} failed to check. "
            "A site may have changed or started blocking the request.",
            token, chat,
        ):
            state["last_error_alert"] = now_utc().isoformat()

    # No `last_run` on purpose: CI commits this file back, and a timestamp that
    # changes every run would mean a commit every few minutes.
    state["alerted_keys"] = sorted(alerted)
    state["chain_status"] = {r.chain: (r.error and f"ERROR: {r.error[:120]}" or r.status) for r in results}
    state["on_sale"] = bool(found)
    if deep:
        state["last_deep_sweep"] = now_utc().isoformat()
    if not args.dry_run:
        save_state(config.STATE_FILE, state)

    # Non-zero only when everything failed - a single flaky chain isn't worth
    # a red X on every run.
    return 1 if errored and len(errored) == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
