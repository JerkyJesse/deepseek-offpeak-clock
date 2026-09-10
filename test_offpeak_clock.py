import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import offpeak_clock


UTC = datetime.timezone.utc


def utc(*args):
    return datetime.datetime(*args, tzinfo=UTC)


def ref_is_peak(t):
    hour = t.hour
    return ((1 <= hour < 4) or (6 <= hour < 10)) and t.weekday() < 5


def scan_flips(start, minutes):
    states = [ref_is_peak(start + datetime.timedelta(minutes=i))
              for i in range(minutes + 1)]
    return [start + datetime.timedelta(minutes=i)
            for i in range(1, minutes + 1) if states[i] != states[i - 1]]


class TestIsPeak(unittest.TestCase):
    def test_weekday_boundaries(self):
        cases = {
            (0, 59): False,
            (1, 0): True,
            (3, 59): True,
            (4, 0): False,
            (5, 59): False,
            (6, 0): True,
            (9, 59): True,
            (10, 0): False,
            (23, 59): False,
        }
        monday = datetime.date(2026, 9, 7)
        for (hour, minute), expected in cases.items():
            t = datetime.datetime.combine(monday, datetime.time(hour, minute), UTC)
            self.assertEqual(offpeak_clock.is_peak(t), expected, msg=str(t))

    def test_weekend_always_off_peak(self):
        saturday = datetime.date(2026, 9, 12)
        for hour in range(24):
            t = datetime.datetime.combine(saturday, datetime.time(hour, 0), UTC)
            self.assertFalse(offpeak_clock.is_peak(t), msg=str(t))
        sunday = saturday + datetime.timedelta(days=1)
        for hour in range(24):
            t = datetime.datetime.combine(sunday, datetime.time(hour, 30), UTC)
            self.assertFalse(offpeak_clock.is_peak(t), msg=str(t))


class TestNextSwitch(unittest.TestCase):
    def test_exact_boundaries(self):
        cases = [
            (utc(2026, 9, 7, 0, 0), utc(2026, 9, 7, 1, 0), "PEAK"),
            (utc(2026, 9, 7, 1, 0), utc(2026, 9, 7, 4, 0), "OFF-PEAK"),
            (utc(2026, 9, 7, 4, 0), utc(2026, 9, 7, 6, 0), "PEAK"),
            (utc(2026, 9, 7, 6, 0), utc(2026, 9, 7, 10, 0), "OFF-PEAK"),
            (utc(2026, 9, 7, 10, 0), utc(2026, 9, 8, 1, 0), "PEAK"),
        ]
        for now, expected_time, expected_target in cases:
            switch, target = offpeak_clock.next_switch(now)
            self.assertEqual(switch, expected_time, msg=str(now))
            self.assertEqual(target, expected_target, msg=str(now))

    def test_weekend_gap_friday_to_monday(self):
        now = utc(2026, 9, 11, 10, 0)
        switch, target = offpeak_clock.next_switch(now)
        self.assertEqual(switch, utc(2026, 9, 14, 1, 0))
        self.assertEqual(target, "PEAK")
        now = utc(2026, 9, 12, 23, 59)
        switch, target = offpeak_clock.next_switch(now)
        self.assertEqual(switch, utc(2026, 9, 14, 1, 0))
        self.assertEqual(target, "PEAK")

    def test_brute_force_against_reference(self):
        start = utc(2026, 9, 4, 0, 0)
        query_minutes = 10 * 24 * 60
        flips = scan_flips(start, query_minutes + 3 * 24 * 60)
        flip_index = 0
        for i in range(query_minutes):
            now = start + datetime.timedelta(minutes=i)
            while flips[flip_index] <= now:
                flip_index += 1
            switch, target = offpeak_clock.next_switch(now)
            self.assertEqual(switch, flips[flip_index], msg=str(now))
            self.assertEqual(target, "PEAK" if ref_is_peak(switch) else "OFF-PEAK",
                             msg=str(now))

    def test_flips_only_on_weekday_hour_marks(self):
        start = utc(2026, 9, 4, 0, 0)
        flips = scan_flips(start, 10 * 24 * 60)
        self.assertTrue(flips)
        for flip in flips:
            self.assertIn(flip.hour, (1, 4, 6, 10), msg=str(flip))
            self.assertEqual(flip.minute, 0, msg=str(flip))
            self.assertLess(flip.weekday(), 5, msg=str(flip))


class TestFormatting(unittest.TestCase):
    def test_fmt_countdown(self):
        self.assertEqual(offpeak_clock.fmt_countdown(datetime.timedelta(seconds=0)),
                         "00:00:00")
        self.assertEqual(offpeak_clock.fmt_countdown(datetime.timedelta(seconds=59)),
                         "00:00:59")
        self.assertEqual(
            offpeak_clock.fmt_countdown(datetime.timedelta(hours=1, minutes=1, seconds=1)),
            "01:01:01")
        self.assertEqual(
            offpeak_clock.fmt_countdown(datetime.timedelta(days=2, hours=3)),
            "2d 03:00:00")


class TestClampPos(unittest.TestCase):
    def test_garbage_input(self):
        self.assertEqual(offpeak_clock._clamp_pos("nope"), offpeak_clock.DEFAULT_POS)
        self.assertEqual(offpeak_clock._clamp_pos((1,)), offpeak_clock.DEFAULT_POS)
        self.assertEqual(offpeak_clock._clamp_pos((1.5, "x")), offpeak_clock.DEFAULT_POS)

    def test_offscreen_recovers(self):
        x, y = offpeak_clock._clamp_pos((-100000, -100000))
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)
        self.assertNotEqual((x, y), (-100000, -100000))
        self.assertGreater(x, -100000)
        self.assertGreater(y, -100000)


class TestConfigLoading(unittest.TestCase):
    def _load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offpeak_clock.json"
            path.write_text(text, encoding="utf-8")
            with mock.patch.object(offpeak_clock, "config_path", return_value=path):
                instance = object.__new__(offpeak_clock.PeakClock)
                return offpeak_clock.PeakClock._load_config(instance)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nope.json"
            with mock.patch.object(offpeak_clock, "config_path", return_value=path):
                instance = object.__new__(offpeak_clock.PeakClock)
                self.assertEqual(offpeak_clock.PeakClock._load_config(instance), {})

    def test_invalid_json(self):
        self.assertEqual(self._load("{not json"), {})

    def test_bad_types_dropped(self):
        cfg = self._load(json.dumps({"pos": ["a", "b"], "topmost": "yes", "extra": 1}))
        self.assertNotIn("pos", cfg)
        self.assertNotIn("topmost", cfg)
        self.assertEqual(cfg.get("extra"), 1)

    def test_legacy_keys_stripped(self):
        cfg = self._load(json.dumps({
            "pos": [1, 2],
            "topmost": False,
            "holidays_off": True,
            "holidays": [],
            "holiday_rules": {},
        }))
        self.assertEqual(cfg, {"pos": [1, 2], "topmost": False})


if __name__ == "__main__":
    unittest.main()
