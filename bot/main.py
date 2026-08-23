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
from .dates import au_date, au_datetime, au_short, au_time, days_until, now_sydney


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


def _link(text: str, url: str | None) -> str:
    text = html.escape(text)
    return f'<a href="{html.escape(url, quote=True)}">{text}</a>' if url else text


def fmt_session(s) -> str:
    """One tappable line: the time itself is the booking link."""
    when = au_time(s.start) if s.start else "Book"
    bits = [f"• {_link(when, s.booking_url)}"]
    if s.screen:
        bits.append(html.escape(s.screen))
    if isinstance(s.seats, int):
        bits.append(f"{s.seats} seats")
    if not s.start and s.note:
        bits.append(html.escape(s.note))
    return "  " + " · ".join(bits)


def build_alert(results: list, new_keys: set) -> str:
    fresh = [s for r in results for s in r.sessions if s.key in new_keys]
    cinemas = {s.cinema for s in fresh}

    lines = [
        f"\U0001f6a8 <b>{html.escape(config.MOVIE_TITLE.upper())} IS ON SALE</b>",
        f"<i>{len(fresh)} sessions across {len(cinemas)} cinemas · "
        f"found {au_datetime(now_sydney())}</i>",
        "",
    ]
    if any(s.members_only for s in fresh):
        lines.insert(2, "\U0001f511 <b>Members-only presale</b> — needs a Cinebuzz account")

    # Rank each venue: IMAX first (it sells out first), then the order the
    # provider declared its venues in, so you see the good screens up top
    # rather than whatever happens to sort alphabetically.
    rank: dict = {}
    for chain_i, r in enumerate(results):
        for venue_i, venue in enumerate(r.venue_order):
            rank[(r.chain, venue)] = (chain_i, venue_i)

    by_cinema: dict = {}
    for s in fresh:
        by_cinema.setdefault((s.chain, s.cinema), []).append(s)

    ordered = sorted(
        by_cinema.items(),
        key=lambda kv: (not kv[1][0].is_imax, rank.get(kv[0], (99, 99)), kv[0]),
    )

    for (chain, cinema), group in ordered[: config.MAX_CINEMAS_LISTED]:
        star = "⭐ " if group[0].is_imax else ""
        lines.append(f"{star}<b>{html.escape(cinema)}</b> · {html.escape(chain)}")

        by_day: dict = {}
        for s in sorted(group, key=lambda s: s.start or ""):
            by_day.setdefault(au_short(s.start) if s.start else "", []).append(s)

        shown = 0
        for day, sessions in by_day.items():
            if shown >= config.MAX_SESSIONS_LISTED:
                break
            if day:
                lines.append(f"  <b>{html.escape(day)}</b>")
            for s in sessions:
                if shown >= config.MAX_SESSIONS_LISTED:
                    break
                lines.append(fmt_session(s))
                shown += 1
        extra = len(group) - shown
        if extra:
            lines.append(f"  <i>+ {extra} more session{'s' if extra > 1 else ''}</i>")
        lines.append("")

    hidden = max(0, len(ordered) - config.MAX_CINEMAS_LISTED)
    if hidden:
        lines.append(f"<i>+ {hidden} more cinema{'s' if hidden > 1 else ''} — full list below</i>")
        lines.append("")

    lines.append("<b>Book direct:</b>")
    for r in results:
        if r.movie_url and any(s.key in new_keys for s in r.sessions):
            lines.append(f"→ {_link(r.chain + ' — all sessions', r.movie_url)}")
    return "\n".join(lines).strip()


def build_heartbeat(results: list, *, requested: bool = False) -> str:
    venues = sum(r.venues for r in results)
    checked = sum(r.checked for r in results)
    days = days_until(config.RELEASE_DATE)

    # Say what actually answered. Claiming 28 when a venue timed out is the
    # kind of small lie that makes you distrust the whole message later.
    coverage = f"{checked} of {venues}" if checked < venues else str(venues)

    lines = [
        f"\U0001f3ac <b>{html.escape(config.MOVIE_TITLE)}</b> — not on sale yet",
        f"<i>{coverage} Sydney cinemas checked · {au_datetime(now_sydney())}</i>",
        "",
    ]
    if requested:
        lines.insert(2, "<i>You asked, so here's a fresh look:</i>")
    for r in results:
        if r.error:
            lines.append(f"⚠️ <b>{html.escape(r.chain)}</b> — check failed")
            lines.append(f"  <i>{html.escape(r.error[:110])}</i>")
        else:
            covered = f"{r.checked}/{r.venues}" if r.checked < r.venues else str(r.venues)
            mark = "✅" if r.checked == r.venues else "🟡"
            lines.append(f"{mark} <b>{_link(r.chain, r.movie_url)}</b> · {covered} venues")
            lines.append(f"  {html.escape(r.status or 'no signal')}")
            if r.failed_venues:
                missed = ", ".join(r.failed_venues[:3])
                more = f" +{len(r.failed_venues) - 3}" if len(r.failed_venues) > 3 else ""
                lines.append(
                    f"  <i>no answer from {html.escape(missed)}{more}"
                    " — retried next run</i>"
                )
    lines.append("")

    tail = f" — {days} days away" if days else ""
    lines.append(f"\U0001f4c5 Release <b>{html.escape(au_date(config.RELEASE_DATE))}</b>{tail}")
    lines.append("<i>Checking every 5 minutes. Next update in 24h.</i>")
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
        ok = telegram.send(
            f"\U0001f9ea <b>{html.escape(config.MOVIE_TITLE)} watch</b> — "
            "notifications are working.",
            token, chat,
        )
        print("sent" if ok else "not delivered")
        return 0 if ok else 1

    state = load_state(config.STATE_FILE)
    alerted = set(state.get("alerted_keys", []))
    deep = args.deep or _cooldown_passed(state.get("last_deep_sweep", ""), config.DEEP_SWEEP_HOURS)

    # Anything you've texted the bot since the last run. Cheap: one request,
    # and it means you can ask for a status report without leaving Telegram.
    requested = False
    if not args.dry_run:
        commands, next_offset = telegram.poll_commands(
            token, chat, state.get("telegram_offset")
        )
        if next_offset is not None:
            state["telegram_offset"] = next_offset
        if commands & telegram.HELP_COMMANDS:
            telegram.send(telegram.help_text(config.MOVIE_TITLE), token, chat)
        if commands & telegram.CHECK_COMMANDS:
            requested = True
            print("  (/check requested via Telegram)")
            deep = True  # an explicit ask deserves the thorough version

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
            print("\n(dry run - not sent, state not advanced)")
        elif telegram.send(body, token, chat):
            alerted |= new_keys
    elif requested and found:
        # Already on sale and already alerted, but you asked - re-send the
        # whole picture rather than the "nothing yet" heartbeat.
        telegram.send(build_alert(results, found), token, chat)
    else:
        print("\nNot on sale yet.")
        heartbeat_due = config.HEARTBEAT_HOURS > 0 and _cooldown_passed(
            state.get("last_heartbeat", ""), config.HEARTBEAT_HOURS
        )
        if not args.dry_run and (requested or args.force_heartbeat or heartbeat_due):
            # A report you asked for should buzz; the daily one shouldn't.
            body = build_heartbeat(results, requested=requested)
            if telegram.send(body, token, chat, silent=not requested):
                state["last_heartbeat"] = now_utc().isoformat()

    if errored and not args.dry_run and _cooldown_passed(state.get("last_error_alert", ""), 12):
        names = ", ".join(r.chain for r in errored)
        detail = next((r.last_error for r in errored if r.last_error), "")
        if telegram.send(
            f"⚠️ <b>{html.escape(config.MOVIE_TITLE)} watch</b>"
            f" — no venues reachable at {html.escape(names)}, so this run"
            f" checked nothing there.\n"
            f"<i>{html.escape(detail[:160])}</i>\n\n"
            "Still retrying every 5 minutes. If this keeps up, the site has "
            "changed or is blocking us.",
            token, chat,
        ):
            state["last_error_alert"] = now_utc().isoformat()

    # No `last_run` on purpose: CI commits this file back, and a timestamp that
    # changes every run would mean a commit every few minutes.
    state["alerted_keys"] = sorted(alerted)
    state["chain_status"] = {
        r.chain: (r.error and f"ERROR: {r.error[:120]}" or r.status) for r in results
    }
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
