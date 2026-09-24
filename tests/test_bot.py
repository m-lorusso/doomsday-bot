"""Offline tests: no network, no Telegram. Run with

    python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.error
import zoneinfo
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import config, dates, http, main, telegram  # noqa: E402
from bot.providers import event, hoyts  # noqa: E402
from bot.providers.base import ProviderResult, Session  # noqa: E402


def args(**kw):
    base = dict(dry_run=False, imax_only=False, force_heartbeat=False, imax_watch=0)
    base.update(kw)
    return SimpleNamespace(**base)


def s(key, *, chain="Event", cinema="George Street", start="2026-12-17T19:00", imax=False, screen="Original"):
    return Session(chain, cinema, key, start, "IMAX" if imax else screen, 100, f"https://book/{key}", imax=imax)


class FakeProvider:
    def __init__(self, name, full=None, imax=None):
        self.name = name
        self.full = full or []  # list of results, consumed in order
        self.imax = imax or []
        self.full_calls = self.imax_calls = 0

    def check(self):
        self.full_calls += 1
        return self.full.pop(0) if len(self.full) > 1 else self.full[0]

    def check_imax(self):
        self.imax_calls += 1
        return self.imax.pop(0) if len(self.imax) > 1 else self.imax[0]


def result(chain, sessions, *, label="IMAX Sydney", venues=16, error=None, imax_error=None, status="on sale"):
    return ProviderResult(
        chain=chain, sessions=list(sessions), venues=venues, checked=0 if error else venues,
        venue_order=["George Street"], status=status, error=error,
        imax_label=label, imax_status="ON SALE" if any(x.imax for x in sessions) else "no sessions yet",
        imax_url="https://imax", imax_error=imax_error,
    )


class BotHarness(unittest.TestCase):
    """Runs Bot against fake providers and a fake Telegram."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.tmp.write("{}")
        self.tmp.close()
        self.sent = []  # (text, silent)
        self.pinned = []
        self.next_id = 100

        def fake_send(text, token, chat, *, silent=False):
            self.sent.append((text, silent))
            self.next_id += 1
            return [self.next_id] if self.deliver else []

        self.deliver = True
        patches = [
            mock.patch.object(config, "STATE_FILE", self.tmp.name),
            mock.patch.object(config, "TELEGRAM_BOT_TOKEN", "t"),
            mock.patch.object(config, "TELEGRAM_CHAT_ID", "1"),
            mock.patch.object(config, "HEARTBEAT_HOURS", 0),
            mock.patch.object(telegram, "send", side_effect=fake_send),
            mock.patch.object(telegram, "pin", side_effect=lambda t, c, mid: self.pinned.append(mid) or True),
            mock.patch.object(telegram, "poll_commands", side_effect=lambda t, c, o: (self.commands.pop(0) if self.commands else set(), o)),
        ]
        self.commands = []
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def bot(self, providers_, **kw):
        with mock.patch.object(main.providers, "build", return_value=providers_):
            return main.Bot(args(**kw))

    def texts(self):
        return [t for t, _ in self.sent]


class ImaxAlerts(BotHarness):
    def test_imax_alert_is_sent_first_pinned_and_followed_by_a_ping(self):
        imax = s("event:1", cinema="IMAX Sydney", imax=True)
        plain = s("event:2")
        b = self.bot([FakeProvider("Event", full=[result("Event", [imax, plain])])])
        b.full_pass()
        texts = self.texts()
        self.assertIn("IMAX IS ON SALE", texts[0])
        self.assertEqual(self.pinned, [101])  # the IMAX alert itself is pinned
        self.assertIn("TICKETS ARE LIVE", texts[1])  # second buzz
        self.assertFalse(self.sent[0][1] or self.sent[1][1])  # both loud
        self.assertIn("IS ON SALE", texts[2])  # then the general alert
        self.assertNotIn("event:1", texts[2])  # IMAX session isn't repeated there
        self.assertIn("see the pinned alert", texts[2])

    def test_later_imax_waves_are_loud_but_only_a_new_screen_is_pinned(self):
        wave1 = result("Event", [s("event:1", cinema="IMAX Sydney", imax=True)])
        wave2 = result("Event", [s("event:1", cinema="IMAX Sydney", imax=True),
                                 s("event:2", cinema="IMAX Sydney", imax=True, start="2026-12-23T19:00")])
        hoyts_opens = result("HOYTS", [s("hoyts:9", chain="HOYTS", cinema="Blacktown", imax=True)], label="Blacktown IMAX")
        ev = FakeProvider("Event", imax=[wave1, wave2, wave2])
        ho = FakeProvider("HOYTS", imax=[result("HOYTS", [], label="Blacktown IMAX"), result("HOYTS", [], label="Blacktown IMAX"), hoyts_opens])
        b = self.bot([ev, ho])
        b.imax_pass()  # IMAX Sydney opens: pinned + ping
        b.imax_pass()  # more at IMAX Sydney: loud, not pinned
        b.imax_pass()  # Blacktown opens: pinned + ping again
        heads = [t.splitlines()[0] for t, _ in self.sent]
        self.assertIn("IMAX IS ON SALE", heads[0])
        self.assertIn("TICKETS ARE LIVE", heads[1])
        self.assertIn("MORE IMAX SESSIONS JUST ADDED", heads[2])
        self.assertFalse(self.sent[2][1])  # still loud
        self.assertIn("IMAX IS ON SALE", heads[3])
        self.assertEqual(len(self.pinned), 2)

    def test_a_crashing_tick_does_not_end_the_watch(self):
        p = FakeProvider("Event", imax=[result("Event", [])])
        b = self.bot([p], imax_only=True)
        clock = {"t": 0.0}
        calls = {"n": 0}
        real = b.imax_pass

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("disk full")
            return real()

        b.imax_pass = flaky
        with (
            mock.patch.object(config, "IMAX_POLL_SECONDS", 1),
            mock.patch.object(main.time, "sleep", side_effect=lambda n: clock.update(t=clock["t"] + n)),
            mock.patch.object(main.time, "monotonic", side_effect=lambda: clock["t"]),
        ):
            b.watch(3)
        self.assertEqual(calls["n"], 3)  # kept going after the first tick blew up

    def test_imax_alert_is_not_repeated(self):
        imax = s("event:1", cinema="IMAX Sydney", imax=True)
        b = self.bot([FakeProvider("Event", imax=[result("Event", [imax])])])
        b.imax_pass()
        b.imax_pass()
        self.assertEqual(sum("IMAX IS ON SALE" in t for t in self.texts()), 1)

    def test_undelivered_imax_alert_is_retried(self):
        imax = s("event:1", cinema="IMAX Sydney", imax=True)
        b = self.bot([FakeProvider("Event", imax=[result("Event", [imax])])])
        self.deliver = False
        b.imax_pass()
        self.assertNotIn("event:1", b.alerted)
        self.assertEqual(self.pinned, [])
        self.deliver = True
        b.imax_pass()
        self.assertIn("event:1", b.alerted)
        self.assertEqual(len(self.pinned), 1)

    def test_imax_alert_is_saved_to_disk_immediately(self):
        imax = s("event:1", cinema="IMAX Sydney", imax=True)
        b = self.bot([FakeProvider("Event", imax=[result("Event", [imax])])])
        b.imax_pass()
        with open(self.tmp.name, encoding="utf-8") as fh:
            self.assertIn("event:1", json.load(fh)["alerted_keys"])

    def test_imax_only_mode_never_sends_general_alerts(self):
        plain = s("event:2")
        b = self.bot([FakeProvider("Event", full=[result("Event", [plain])])], imax_only=True)
        b.full_pass(general=False)
        self.assertEqual(self.sent, [])


class GeneralAlerts(BotHarness):
    def test_first_general_alert_is_loud_later_ones_quiet(self):
        p = FakeProvider("Event", full=[result("Event", [s("event:1")]), result("Event", [s("event:1"), s("event:2")])])
        b = self.bot([p])
        b.full_pass()
        b.full_pass()
        (first, first_silent), (second, second_silent) = self.sent
        self.assertIn("IS ON SALE", first)
        self.assertFalse(first_silent)
        self.assertIn("1 new Avengers: Doomsday session", second)
        self.assertTrue(second_silent)

    def test_existing_state_counts_as_already_announced(self):
        with open(self.tmp.name, "w", encoding="utf-8") as fh:
            json.dump({"alerted_keys": ["event:1"], "last_deep_sweep": "x"}, fh)
        b = self.bot([FakeProvider("Event", full=[result("Event", [s("event:1"), s("event:2")])])])
        b.full_pass()
        self.assertTrue(self.sent[0][1])  # quiet: the big announcement already happened
        b.save()
        with open(self.tmp.name, encoding="utf-8") as fh:
            self.assertNotIn("last_deep_sweep", json.load(fh))

    def test_error_alert_only_when_a_whole_chain_fails(self):
        ok = result("Event", [], status="listed")
        ok.missed = ["18 Dec"]  # partial trouble: reported, not alerted
        b = self.bot([FakeProvider("Event", full=[ok])])
        b.full_pass()
        self.assertEqual(self.sent, [])
        dead = result("HOYTS", [], error="HTTP 403", label="Blacktown IMAX")
        dead.last_error = "HTTP 403"
        b = self.bot([FakeProvider("HOYTS", full=[dead])])
        b.full_pass()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("couldn't reach any venue", self.sent[0][0])


class Commands(BotHarness):
    def test_check_replies_loudly_with_imax_front_and_centre(self):
        self.commands = [{"/check"}]
        b = self.bot([FakeProvider("Event", full=[result("Event", [])])], imax_only=True)
        out = b.handle(b.poll())
        self.assertIsNotNone(out)
        text, silent = self.sent[-1]
        self.assertFalse(silent)
        self.assertIn("<b>IMAX</b>", text)
        self.assertIn("You asked", text)

    def test_watch_loop_checks_imax_each_tick_and_honours_check(self):
        p = FakeProvider("Event", full=[result("Event", [])], imax=[result("Event", [])])
        b = self.bot([p], imax_only=True)
        self.commands = [set(), {"/check"}, set()]
        clock = {"t": 0.0}  # only moves when the loop sleeps
        with (
            mock.patch.object(config, "IMAX_POLL_SECONDS", 1),
            mock.patch.object(main.time, "sleep", side_effect=lambda n: clock.update(t=clock["t"] + n)),
            mock.patch.object(main.time, "monotonic", side_effect=lambda: clock["t"]),
        ):
            b.watch(3)  # three one-second ticks
        self.assertEqual(p.full_calls, 1)  # the /check
        self.assertEqual(p.imax_calls, 2)  # the other two ticks


class Messages(unittest.TestCase):
    def test_headlines(self):
        none = [result("Event", [], status="listed")]
        sale = [result("Event", [s("event:1")])]
        imax = [result("Event", [s("event:1", imax=True)])]
        self.assertIn("not on sale yet", main.build_status(none))
        self.assertIn("on sale, but not in IMAX yet", main.build_status(sale))
        self.assertIn("IMAX ON SALE", main.build_status(imax))

    def test_coverage_is_honest(self):
        r = result("Event", [])
        r.checked = 15
        self.assertIn("15 of 16 Sydney cinemas checked", main.build_status([r]))

    def test_test_imax_alert_is_labelled(self):
        sessions, results = main.sample_imax()
        text = main.build_imax_alert(sessions, results, test=True)
        self.assertTrue(text.startswith("\U0001f9ea <b>TEST"))
        self.assertIn("BOOK IMAX SYDNEY NOW", text)
        self.assertIn("BOOK BLACKTOWN IMAX NOW", text)
        self.assertLess(len(text), telegram.LIMIT)  # one message, one pin


class ImaxDetection(unittest.TestCase):
    def test_hoyts_uses_the_screen_not_the_venue(self):
        p = hoyts.HoytsProvider(config)
        std = p._session({"id": 1, "typeId": "STANDARD", "screenName": "Cinema 02", "date": "2026-12-16T18:00"}, "Blacktown")
        imx = p._session({"id": 2, "typeId": "IMAX", "screenName": "IMAX 01", "date": "2026-12-16T18:00"}, "Blacktown")
        by_name = p._session({"id": 3, "typeId": "PREMIUM", "screenName": "IMAX 01", "date": "2026-12-16T18:00"}, "Blacktown")
        self.assertFalse(std.imax)
        self.assertTrue(imx.imax)
        self.assertTrue(by_name.imax)

    def test_hoyts_picks_up_an_imax_version_under_a_new_film_code(self):
        p = hoyts.HoytsProvider(config)
        films_v1 = [{"name": "Avengers: Doomsday", "vistaId": "HO1,HO2", "link": "/movies/avengers-doomsday"}]
        films_v2 = films_v1 + [{"name": "Avengers: Doomsday (IMAX)", "vistaId": "HO9"}]
        venue = [{"id": 7, "movieId": "HO9", "typeId": "IMAX", "screenName": "IMAX 01", "date": "2026-12-16T18:00"}]
        calls = iter([films_v1, venue, films_v2])
        with mock.patch.object(http, "fetch_json", side_effect=lambda *a, **k: next(calls)), \
             mock.patch.object(hoyts, "TITLES_MIN_GAP", -1):
            r = p.check_imax()
        self.assertEqual([x.key for x in r.sessions], ["hoyts:7"])

    def test_event_marks_imax_sydney_and_imax_screens_only(self):
        p = event.EventProvider(config)
        data = {"Movies": [{"Name": "Avengers: Doomsday", "CinemaModels": [
            {"Id": 96, "Sessions": [{"Id": 1, "ScreenTypeName": "IMAX"}]},
            {"Id": 15, "Sessions": [{"Id": 2, "ScreenTypeName": "V-Max"}]},
        ]}]}
        got = {x.key: x.imax for x in p._harvest(data)}
        self.assertEqual(got, {"event:1": True, "event:2": False})

    def test_event_probes_dates_nearest_the_release_first(self):
        p = event.EventProvider(config)
        dates_ = ["2026-11-01", "2026-12-13", "2026-12-14", "2026-12-16", "2026-12-17", "2026-12-18", "2027-01-20"]
        with mock.patch.object(config, "WATCH_FROM", "2026-12-14"), mock.patch.object(config, "RELEASE_DATE", "2026-12-17"):
            self.assertEqual(p._far_dates(dates_, cap=3), ["2026-12-16", "2026-12-18", "2026-12-14"])

    def test_event_gives_up_after_consecutive_failures(self):
        p = event.EventProvider(config)
        p._warm = True
        calls = {"n": 0}

        def fake(url, **kw):
            calls["n"] += 1
            if "cinemaIds=15" in url and "2026-12-17" in url:  # the all-venue primary request
                return {"Success": True, "Data": {"Dates": [f"2026-12-{d}" for d in range(14, 31)], "Movies": []}}
            if "2026-12-17" in url:  # IMAX Sydney primary
                return {"Success": True, "Data": {"Dates": [], "Movies": []}}
            raise http.FetchError("403")

        with mock.patch.object(http, "fetch_json", side_effect=fake), mock.patch.object(event.time, "sleep"):
            r = p.check()
        self.assertEqual(calls["n"], 2 + event.GIVE_UP_AFTER)
        self.assertIn("later dates", r.missed)
        self.assertIsNone(r.error)  # the venues answered; only follow-ups failed


class Plumbing(unittest.TestCase):
    def test_poll_ignores_strangers(self):
        data = {"result": [
            {"update_id": 5, "message": {"chat": {"id": 1}, "text": "/imax@DOOMSDAYbot"}},
            {"update_id": 6, "message": {"chat": {"id": 999}, "text": "/check"}},
        ]}
        with mock.patch.object(telegram, "_api", return_value=data):
            cmds, off = telegram.poll_commands("t", "1", None)
        self.assertEqual(cmds, {"/imax"})
        self.assertEqual(off, 7)

    def test_html_instead_of_json_is_a_fetch_error(self):
        with mock.patch.object(http, "fetch", return_value=b"<!DOCTYPE html>Just a moment"):
            with self.assertRaises(http.FetchError):
                http.fetch_json("https://x")

    def test_sydney_offset_both_paths(self):
        cases = [("2026-09-25T06:00", 10), ("2026-10-03T16:00", 11), ("2026-12-17T08:00", 11), ("2027-04-03T16:00", 10)]
        for iso, want in cases:
            u = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
            self.assertEqual(dates.sydney_offset(u).total_seconds() / 3600, want, iso)
            with mock.patch.object(zoneinfo, "ZoneInfo", side_effect=zoneinfo.ZoneInfoNotFoundError):
                self.assertEqual(dates.sydney_offset(u).total_seconds() / 3600, want, iso + " (fallback)")

    def test_blocked_requests_back_off_longer(self):
        blocked = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        self.assertEqual(http._backoff(blocked, 0), 4)
        self.assertEqual(http._backoff(ValueError(), 0), 1)


if __name__ == "__main__":
    unittest.main()
