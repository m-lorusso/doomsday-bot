"""Watch Sydney cinemas for Avengers: Doomsday, with IMAX treated as the thing
that actually matters.

    python -m bot.main                       one full check (what GitHub runs)
    python -m bot.main --imax-watch 3600     ...then keep watching IMAX every
                                             minute for an hour
    python -m bot.main --imax-only --imax-watch 21600
                                             IMAX-only watcher (what this PC runs)
    python -m bot.main --dry-run             print instead of sending; save nothing
    python -m bot.main --test-alert          prove Telegram delivery works
    python -m bot.main --test-imax           send a clearly-marked sample IMAX alert

What gets sent:

  * IMAX on sale   - its own loud message, pinned to the top of the chat, then
                     a second short message so the phone buzzes twice.
  * General sale   - the first time: a loud "on sale" alert. After that, newly
                     added (non-IMAX) sessions arrive as quiet updates, so they
                     don't dilute the IMAX alert.
  * Daily status   - silent, and it always says where IMAX stands.
"""

import argparse
import html
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config, providers, telegram
from .dates import au_date, au_datetime, au_short, au_time, days_until, now_sydney
from .providers.base import ProviderResult, Session

# Emoji, spelled out so the source stays plain ASCII.
SIREN, TICKET, POINT, RED = "\U0001f6a8", "\U0001f39f️", "\U0001f449", "\U0001f7e5"
OK, WAIT, WARN, AMBER = "✅", "⏳", "⚠️", "\U0001f7e1"
FILM, CAL, KEY, PLUS, TEST = "\U0001f3ac", "\U0001f4c5", "\U0001f511", "➕", "\U0001f9ea"
DOT, DASH, BULLET, ARROW = "·", "—", "•", "→"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def esc(text) -> str:
    return html.escape(str(text))


def _link(text: str, url: str | None) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{esc(text)}</a>' if url else esc(text)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


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


def cooldown_passed(iso: str | None, hours: float) -> bool:
    if not iso:
        return True
    try:
        last = datetime.fromisoformat(iso)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now_utc() - last >= timedelta(hours=hours)


# --- message building -------------------------------------------------------


def fmt_session(s: Session, bullet: str = BULLET) -> str:
    """One tappable line: the time itself is the booking link."""
    when = au_time(s.start) if s.start else "Book"
    bits = [f"{bullet} {_link(when, s.booking_url)}"]
    if s.screen:
        bits.append(esc(s.screen))
    if isinstance(s.seats, int):
        bits.append(f"{s.seats} seats")
    if not s.start and s.note:
        bits.append(esc(s.note))
    return "  " + f" {DOT} ".join(bits)


def _by_day(sessions: list, limit: int, bullet: str = BULLET) -> list:
    """Sessions grouped under day headings, earliest first, capped at `limit`."""
    lines, shown, current_day = [], 0, None
    for s in sorted(sessions, key=lambda s: s.start or ""):
        if shown >= limit:
            break
        day = au_short(s.start) if s.start else ""
        if day and day != current_day:
            lines.append(f"  <b>{esc(day)}</b>")
            current_day = day
        lines.append(fmt_session(s, bullet))
        shown += 1
    if len(sessions) > shown:
        lines.append(f"  <i>+ {len(sessions) - shown} more</i>")
    return lines


def _chain_rank(chain: str) -> int:
    return config.CHAINS.index(chain.lower()) if chain.lower() in config.CHAINS else 99


def build_imax_alert(sessions: list, results: list, *, test: bool = False, more: bool = False) -> str:
    where = {r.chain: (r.imax_label, r.imax_url) for r in results}
    venues: dict = {}
    for s in sessions:
        label, url = where.get(s.chain, (None, None))
        venues.setdefault((s.chain, label or s.cinema, url), []).append(s)

    lines = []
    if test:
        lines += [f"{TEST} <b>TEST {DASH} nothing is on sale.</b> This is what the real IMAX alert looks like.", ""]
    lines += [
        f"{RED} <b>MORE IMAX SESSIONS JUST ADDED</b>" if more
        else f"{SIREN}{SIREN}{SIREN} <b>IMAX IS ON SALE</b> {SIREN}{SIREN}{SIREN}",
        f"<b>{esc(config.MOVIE_TITLE.upper())}</b>",
        f"<i>{_plural(len(sessions), 'IMAX session')} {DOT} found {au_datetime(now_sydney())}</i>",
    ]
    if any(s.members_only for s in sessions):
        lines.append(f"{KEY} <b>Members-only presale</b> {DASH} log in to Cinebuzz first")
    lines.append("")

    for (chain, label, url), group in sorted(venues.items(), key=lambda kv: _chain_rank(kv[0][0])):
        lines.append(f"{RED} <b>{esc(label.upper())}</b> {DOT} {esc(chain)} {DASH} {_plural(len(group), 'session')}")
        lines += _by_day(group, config.IMAX_SESSIONS_LISTED, bullet=TICKET)
        book = url or group[0].booking_url
        if book:
            lines.append(f"{POINT} <b>{_link('BOOK ' + label.upper() + ' NOW', book)}</b>")
        lines.append("")
    lines.append("<i>Tap a time to jump straight to seat selection.</i>")
    return "\n".join(lines)


def build_imax_ping() -> str:
    # A second, short message: two buzzes in a row are much harder to miss.
    return f"‼️ <b>IMAX {esc(config.MOVIE_MATCH.upper())} TICKETS ARE LIVE</b> {DASH} open the pinned message ☝️"


def build_alert(results: list, keys: set, *, first: bool) -> str:
    """General (non-IMAX) sessions. Loud the first time, a quiet update after."""
    fresh = [s for r in results for s in r.sessions if s.key in keys]
    cinemas = {(s.chain, s.cinema) for s in fresh}
    title = config.MOVIE_TITLE
    stamp = au_datetime(now_sydney())

    if first:
        lines = [
            f"{SIREN} <b>{esc(title.upper())} IS ON SALE</b>",
            f"<i>{_plural(len(fresh), 'session')} across {_plural(len(cinemas), 'cinema')} {DOT} found {stamp}</i>",
        ]
    else:
        lines = [
            f"{PLUS} <b>{_plural(len(fresh), 'new ' + title + ' session')}</b> across {_plural(len(cinemas), 'cinema')}",
            f"<i>found {stamp} {DOT} not IMAX</i>",
        ]
    if any(s.members_only for s in fresh):
        lines.append(f"{KEY} <b>Members-only presale</b> {DASH} needs a Cinebuzz account")
    imax_live = any(r.imax_sessions for r in results)
    lines.append(
        f"{TICKET} IMAX: "
        + ("on sale — see the pinned alert" if imax_live
           else "not on sale yet — you'll get a separate, pinned alert the moment it is")
    )
    lines.append("")

    rank = {}
    for ci, r in enumerate(results):
        for vi, venue in enumerate(r.venue_order):
            rank[(r.chain, venue)] = (ci, vi)
    by_cinema: dict = {}
    for s in fresh:
        by_cinema.setdefault((s.chain, s.cinema), []).append(s)
    ordered = sorted(by_cinema.items(), key=lambda kv: (rank.get(kv[0], (99, 99)), kv[0]))

    for (chain, cinema), group in ordered[: config.MAX_CINEMAS_LISTED]:
        lines.append(f"<b>{esc(cinema)}</b> {DOT} {esc(chain)}")
        lines += _by_day(group, config.MAX_SESSIONS_LISTED)
        lines.append("")
    hidden = len(ordered) - config.MAX_CINEMAS_LISTED
    if hidden > 0:
        lines += [f"<i>+ {_plural(hidden, 'more cinema')} {DASH} full list below</i>", ""]

    lines.append("<b>Book direct:</b>")
    for r in results:
        if r.movie_url and any(s.key in keys for s in r.sessions):
            lines.append(f"{ARROW} {_link(r.chain + ' ' + DASH + ' all sessions', r.movie_url)}")
    return "\n".join(lines).strip()


def _imax_lines(results: list) -> list:
    lines = [f"{TICKET} <b>IMAX</b>"]
    for r in results:
        if not r.imax_label:
            continue
        if r.imax_error:
            icon, text = WARN, f"check failed {DASH} {r.imax_error[:90]}"
        elif r.imax_sessions:
            icon, text = OK, r.imax_status or "on sale"
        else:
            icon, text = WAIT, r.imax_status or "no answer"
        lines.append(f"{icon} <b>{esc(r.imax_label)}</b> {DOT} {esc(r.chain)}")
        lines.append(f"   {esc(text)}")
        if r.imax_sessions and r.imax_url:
            lines.append(f"   {POINT} {_link('Book IMAX', r.imax_url)}")
    return lines


def build_status(results: list, *, requested: bool = False) -> str:
    venues = sum(r.venues for r in results)
    checked = sum(r.checked for r in results)
    on_sale = any(r.sessions for r in results)
    imax_on = any(r.imax_sessions for r in results)
    if imax_on:
        headline = f"{SIREN} IMAX ON SALE"
    elif on_sale:
        headline = "on sale, but not in IMAX yet"
    else:
        headline = "not on sale yet"

    # Say what actually answered. Claiming 28 when a venue timed out is the
    # kind of small lie that makes you distrust the whole message later.
    coverage = f"{checked} of {venues}" if checked < venues else str(venues)
    lines = [
        f"{FILM} <b>{esc(config.MOVIE_TITLE)}</b> {DASH} {headline}",
        f"<i>{coverage} Sydney cinemas checked {DOT} {au_datetime(now_sydney())}</i>",
    ]
    if requested:
        lines.append("<i>You asked, so here's a fresh look.</i>")
    lines.append("")
    lines += _imax_lines(results)
    lines.append("")

    for r in results:
        if r.error:
            lines.append(f"{WARN} <b>{esc(r.chain)}</b> {DASH} check failed")
            lines.append(f"  <i>{esc(r.error[:110])}</i>")
            continue
        whole = r.checked == r.venues and not r.missed
        covered = str(r.venues) if r.checked == r.venues else f"{r.checked}/{r.venues}"
        lines.append(f"{OK if whole else AMBER} <b>{_link(r.chain, r.movie_url)}</b> {DOT} {covered} venues")
        lines.append(f"  {esc(r.status or 'no signal')}")
        if r.missed:
            shown = ", ".join(r.missed[:3]) + (f" +{len(r.missed) - 3}" if len(r.missed) > 3 else "")
            lines.append(f"  <i>no answer for {esc(shown)} {DASH} retried next run</i>")
    lines.append("")

    days = days_until(config.RELEASE_DATE)
    tail = f" {DASH} {_plural(days, 'day')} away" if days and days > 0 else ""
    lines.append(f"{CAL} Release <b>{esc(au_date(config.RELEASE_DATE))}</b>{tail}")
    lines.append("<i>IMAX gets its own loud, pinned alert the moment it opens.</i>")
    return "\n".join(lines)


def build_imax_status(results: list) -> str:
    return "\n".join(
        [f"{FILM} <b>{esc(config.MOVIE_TITLE)}</b> {DASH} IMAX check",
         f"<i>{au_datetime(now_sydney())}</i>", ""] + _imax_lines(results)
    )


def sample_imax() -> tuple:
    """Plausible, clearly fake sessions for --test-imax."""
    ev = "https://www.eventcinemas.com.au/movie/avengers-doomsday#cinemas=96"
    ho = "https://www.hoyts.com.au/movies/avengers-doomsday"
    sessions = [
        Session("Event", "IMAX Sydney", "test:1", "2026-12-16T18:00", "IMAX", 214, ev, imax=True),
        Session("Event", "IMAX Sydney", "test:2", "2026-12-16T21:45", "IMAX", 301, ev, imax=True),
        Session("Event", "IMAX Sydney", "test:3", "2026-12-17T09:30", "IMAX", 355, ev, imax=True),
        Session("HOYTS", "Blacktown", "test:4", "2026-12-16T18:30", "IMAX", None, ho, imax=True),
        Session("HOYTS", "Blacktown", "test:5", "2026-12-16T22:15", "IMAX", None, ho, imax=True),
    ]
    results = [
        ProviderResult(chain="Event", imax_label="IMAX Sydney", imax_url=ev),
        ProviderResult(chain="HOYTS", imax_label="Blacktown IMAX", imax_url=ho),
    ]
    return sessions, results


# --- the bot ------------------------------------------------------------------


class Bot:
    def __init__(self, args):
        self.args = args
        self.token, self.chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
        self.state = load_state(config.STATE_FILE)
        # Older state files: the deep-sweep timestamp is gone, and anything
        # already alerted means the big "on sale" announcement has been made.
        self.state.pop("last_deep_sweep", None)
        self.state.setdefault("announced_on_sale", bool(self.state.get("alerted_keys")))
        self.alerted = set(self.state.get("alerted_keys", []))
        self.providers = providers.build(config)
        self.imax_view: dict = {}  # chain -> latest result carrying IMAX fields

    # --- plumbing -------------------------------------------------------------

    def log(self, msg: str) -> None:
        print(f"[{now_sydney():%d/%m %H:%M:%S}] {msg}", flush=True)

    def send(self, text: str, *, silent: bool = False) -> list:
        if self.args.dry_run:
            print(f"\n--- would send{' (silent)' if silent else ''} ---\n{text}\n---", flush=True)
            return []  # nothing is recorded as delivered on a dry run
        return telegram.send(text, self.token, self.chat, silent=silent)

    def save(self) -> None:
        if self.args.dry_run:
            return
        self.state["alerted_keys"] = sorted(self.alerted)
        save_state(config.STATE_FILE, self.state)

    def poll(self) -> set:
        if self.args.dry_run:
            return set()
        commands, offset = telegram.poll_commands(self.token, self.chat, self.state.get("telegram_offset"))
        if offset is not None:
            self.state["telegram_offset"] = offset
        if commands:
            self.log(f"commands: {' '.join(sorted(commands))}")
        if commands & telegram.HELP_COMMANDS:
            self.send(telegram.help_text(esc(config.MOVIE_TITLE)))
        return commands

    def _run(self, method: str) -> list:
        results = []
        for provider in self.providers:
            try:
                r = getattr(provider, method)()
            except Exception as exc:  # noqa: BLE001 - one bad chain shouldn't kill the run
                r = ProviderResult(chain=provider.name, error=f"unhandled: {exc}", imax_error=f"unhandled: {exc}")
            results.append(r)
            if r.imax_label or r.imax_error:
                self.imax_view[r.chain] = r
        return results

    # --- alerts ---------------------------------------------------------------

    def alert_imax(self, results: list) -> None:
        new = [s for r in results for s in r.imax_sessions if s.key not in self.alerted]
        if not new:
            return
        # Pin and double-buzz when a screen opens for the first time. Later
        # waves at an already-open screen are still loud, just not re-pinned.
        opened = set(self.state.get("imax_alerted_chains", []))
        opening = {s.chain for s in new} - opened
        self.log(f"IMAX ON SALE: {len(new)} new IMAX sessions" + (f", opening {sorted(opening)}" if opening else ""))
        ids = self.send(build_imax_alert(new, results, more=not opening))
        if not ids:
            return  # not delivered - leave unrecorded so the next tick retries
        self.alerted |= {s.key for s in new}
        self.state["imax_on_sale"] = True
        self.state["imax_alerted_chains"] = sorted(opened | {s.chain for s in new})
        self.save()  # record it now, before anything else can go wrong
        if opening:
            telegram.pin(self.token, self.chat, ids[0])
            self.send(build_imax_ping())

    def alert_general(self, results: list) -> None:
        keys = {s.key for r in results for s in r.sessions if not s.imax and s.key not in self.alerted}
        if not keys:
            return
        first = not self.state.get("announced_on_sale")
        self.log(f"{'ON SALE' if first else 'new sessions'}: {len(keys)}")
        if self.send(build_alert(results, keys, first=first), silent=not first):
            self.alerted |= keys
            self.state["announced_on_sale"] = True
            self.save()

    def alert_errors(self, results: list) -> None:
        failed = [r for r in results if r.error]
        if not failed or not cooldown_passed(self.state.get("last_error_alert"), config.ERROR_ALERT_HOURS):
            return
        names = ", ".join(r.chain for r in failed)
        detail = next((r.last_error for r in failed if r.last_error), "")
        sent = self.send(
            f"{WARN} <b>{esc(config.MOVIE_TITLE)} watch</b> {DASH} couldn't reach any venue at "
            f"{esc(names)}, so this check saw nothing there.\n<i>{esc(detail[:160])}</i>\n\n"
            "Still retrying. If this keeps up, the site has changed or is blocking us."
        )
        if sent:
            self.state["last_error_alert"] = now_utc().isoformat()

    def alert_imax_failures(self, results: list) -> None:
        """Say so if an IMAX check has been failing for a while."""
        failing = self.state.setdefault("imax_failing_since", {})
        for r in results:
            if not r.imax_error:
                failing.pop(r.chain, None)
            else:
                failing.setdefault(r.chain, now_utc().isoformat())
        stuck = [c for c, since in failing.items() if cooldown_passed(since, config.IMAX_FAIL_ALERT_MINUTES / 60)]
        if not stuck or not cooldown_passed(self.state.get("last_error_alert"), config.ERROR_ALERT_HOURS):
            return
        sent = self.send(
            f"{WARN} <b>IMAX checks failing</b> at {esc(', '.join(stuck))} for "
            f"{config.IMAX_FAIL_ALERT_MINUTES}+ minutes. Still retrying every minute."
        )
        if sent:
            self.state["last_error_alert"] = now_utc().isoformat()

    # --- passes ---------------------------------------------------------------

    def full_pass(self, *, requested: bool = False, general: bool = True) -> list:
        t = time.monotonic()
        results = self._run("check")
        for r in results:
            self.log(
                f"{r.chain:<6} {r.checked}/{r.venues} venues  {r.status or ''}"
                f"  | IMAX: {r.imax_error or r.imax_status}"
                + (f"  | ERROR {r.error}" if r.error else "")
                + (f"  | missed {', '.join(r.missed)}" if r.missed else "")
            )
        self.log(f"full check took {time.monotonic() - t:.1f}s")

        self.alert_imax(results)  # always first
        if general:
            self.alert_general(results)

        self.state["chain_status"] = {r.chain: (f"ERROR: {r.error[:120]}" if r.error else r.status) for r in results}
        self.state["imax_status"] = {
            r.imax_label: (f"ERROR: {r.imax_error[:120]}" if r.imax_error else r.imax_status)
            for r in results if r.imax_label
        }
        if not any(r.error for r in results):
            self.state["on_sale"] = any(r.sessions for r in results)

        if requested:
            self.send(build_status(results, requested=True))  # you asked: this one buzzes
        elif general and (
            self.args.force_heartbeat
            or (config.HEARTBEAT_HOURS > 0 and cooldown_passed(self.state.get("last_heartbeat"), config.HEARTBEAT_HOURS))
        ):
            if self.send(build_status(results), silent=True):
                self.state["last_heartbeat"] = now_utc().isoformat()

        self.alert_errors(results)
        self.alert_imax_failures(results)
        return results

    def imax_pass(self) -> list:
        results = self._run("check_imax")
        self.log("IMAX  " + "  | ".join(f"{r.imax_label or r.chain}: {r.imax_error or r.imax_status}" for r in results))
        self.alert_imax(results)
        self.state["imax_status"] = {
            r.imax_label: (f"ERROR: {r.imax_error[:120]}" if r.imax_error else r.imax_status)
            for r in results if r.imax_label
        }
        self.alert_imax_failures(results)
        return results

    def handle(self, commands: set) -> list | None:
        """Act on /check. Returns the full check's results if one ran."""
        if commands & telegram.CHECK_COMMANDS:
            return self.full_pass(requested=True, general=not self.args.imax_only)
        return None

    def reply_imax(self, commands: set) -> None:
        if commands & telegram.IMAX_COMMANDS:
            self.send(build_imax_status(list(self.imax_view.values())))

    def watch(self, seconds: int) -> None:
        """Keep checking IMAX every IMAX_POLL_SECONDS until `seconds` are up."""
        deadline = time.monotonic() + seconds
        next_full = time.monotonic() + config.FULL_CHECK_MINUTES * 60
        self.log(f"watching IMAX every {config.IMAX_POLL_SECONDS}s for " + (f"{seconds // 60} min" if seconds >= 120 else f"{seconds}s"))
        while time.monotonic() + config.IMAX_POLL_SECONDS <= deadline:
            time.sleep(config.IMAX_POLL_SECONDS)
            try:
                commands = self.poll()
                if self.handle(commands) is not None:
                    next_full = time.monotonic() + config.FULL_CHECK_MINUTES * 60
                elif not self.args.imax_only and time.monotonic() >= next_full:
                    self.full_pass()
                    next_full = time.monotonic() + config.FULL_CHECK_MINUTES * 60
                else:
                    self.imax_pass()
                self.reply_imax(commands)
                self.save()
            except Exception as exc:  # noqa: BLE001 - one bad tick must not end the watch
                self.log(f"tick failed, carrying on: {exc!r}")


# --- entry point ------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watch Sydney cinemas (IMAX first) for a movie going on sale.")
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending; save nothing")
    ap.add_argument("--test-alert", action="store_true", help="send a test message and exit")
    ap.add_argument("--test-imax", action="store_true", help="send a clearly-marked sample IMAX alert and exit")
    ap.add_argument("--force-heartbeat", action="store_true", help="send the status report now")
    ap.add_argument("--imax-only", action="store_true",
                    help="IMAX alerts only (plus /check replies) - for a second watcher alongside GitHub")
    ap.add_argument("--imax-watch", type=int, default=0, metavar="SECONDS",
                    help="after the first pass, keep checking IMAX every minute for this long")
    args = ap.parse_args(argv)

    if config.LOG_FILE:
        sys.stdout = sys.stderr = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
    else:
        # Windows consoles and redirected output default to a codepage that
        # can't print emoji; never let a print() be what crashes the watcher.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    token, chat = config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
    if args.test_alert:
        ok = telegram.send(f"{TEST} <b>{esc(config.MOVIE_TITLE)} watch</b> {DASH} notifications are working.", token, chat)
        print("sent" if ok else "not delivered")
        return 0 if ok else 1
    if args.test_imax:
        sessions, results = sample_imax()
        ok = telegram.send(build_imax_alert(sessions, results, test=True), token, chat)
        print("sent" if ok else "not delivered")
        return 0 if ok else 1

    bot = Bot(args)
    commands = bot.poll()
    first = bot.handle(commands)
    if first is None:
        first = bot.imax_pass() if args.imax_only else bot.full_pass()
    bot.reply_imax(commands)
    bot.save()

    if args.imax_watch > 0:
        try:
            bot.watch(args.imax_watch)
        except KeyboardInterrupt:
            bot.log("stopped")
        finally:
            bot.save()

    # Non-zero only when every chain failed outright - one flaky chain isn't
    # worth a red X on every run.
    failed = [r for r in first if r.error or (args.imax_only and r.imax_error)]
    return 1 if first and len(failed) == len(first) else 0


if __name__ == "__main__":
    sys.exit(main())
