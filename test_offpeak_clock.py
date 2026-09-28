import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import offpeak_clock


UTC = datetime.timezone.utc
BJ = datetime.timezone(datetime.timedelta(hours=8))


def utc(*args):
    return datetime.datetime(*args, tzinfo=UTC)


# Independent copy of the State Council 2026 rest dates (国办发明电〔2025〕7号).
CN_HOLIDAYS_2026 = {
    datetime.date(2026, 1, 1), datetime.date(2026, 1, 2), datetime.date(2026, 1, 3),
    datetime.date(2026, 2, 15), datetime.date(2026, 2, 16), datetime.date(2026, 2, 17),
    datetime.date(2026, 2, 18), datetime.date(2026, 2, 19), datetime.date(2026, 2, 20),
    datetime.date(2026, 2, 21), datetime.date(2026, 2, 22), datetime.date(2026, 2, 23),
    datetime.date(2026, 4, 4), datetime.date(2026, 4, 5), datetime.date(2026, 4, 6),
    datetime.date(2026, 5, 1), datetime.date(2026, 5, 2), datetime.date(2026, 5, 3),
    datetime.date(2026, 5, 4), datetime.date(2026, 5, 5),
    datetime.date(2026, 6, 19), datetime.date(2026, 6, 20), datetime.date(2026, 6, 21),
    datetime.date(2026, 9, 25), datetime.date(2026, 9, 26), datetime.date(2026, 9, 27),
    datetime.date(2026, 10, 1), datetime.date(2026, 10, 2), datetime.date(2026, 10, 3),
    datetime.date(2026, 10, 4), datetime.date(2026, 10, 5), datetime.date(2026, 10, 6),
    datetime.date(2026, 10, 7),
}


def ref_is_peak(t):
    bj = t.astimezone(BJ)
    hour = bj.hour
    if not ((9 <= hour < 12) or (14 <= hour < 18)):
        return False
    if bj.weekday() >= 5:
        return False
    return bj.date() not in CN_HOLIDAYS_2026


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

    def test_embedded_holidays_off_peak_in_window(self):
        cases = [
            utc(2026, 1, 1, 2, 0),
            utc(2026, 2, 20, 2, 0),
            utc(2026, 4, 6, 6, 30),
            utc(2026, 5, 1, 2, 0),
            utc(2026, 6, 19, 2, 0),
            utc(2026, 9, 25, 6, 30),
            utc(2026, 10, 7, 2, 0),
        ]
        for t in cases:
            self.assertFalse(offpeak_clock.is_peak(t), msg=str(t))
        self.assertTrue(offpeak_clock.is_peak(utc(2026, 10, 8, 2, 0)))

    def test_makeup_workday_weekend_stays_off_peak(self):
        self.assertFalse(offpeak_clock.is_peak(utc(2026, 9, 20, 2, 0)))
        self.assertFalse(offpeak_clock.is_peak(utc(2026, 10, 10, 2, 0)))


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

    def test_national_day_gap(self):
        switch, target = offpeak_clock.next_switch(utc(2026, 9, 30, 23, 0))
        self.assertEqual(switch, utc(2026, 10, 8, 1, 0))
        self.assertEqual(target, "PEAK")

    def test_spring_festival_gap_exceeds_one_week(self):
        switch, target = offpeak_clock.next_switch(utc(2026, 2, 13, 10, 0))
        self.assertEqual(switch, utc(2026, 2, 24, 1, 0))
        self.assertEqual(target, "PEAK")

    def test_sunday_holiday_weekend_gap(self):
        switch, target = offpeak_clock.next_switch(utc(2026, 9, 27, 20, 0))
        self.assertEqual(switch, utc(2026, 9, 28, 1, 0))
        self.assertEqual(target, "PEAK")

    def test_makeup_saturday_gap(self):
        switch, target = offpeak_clock.next_switch(utc(2026, 10, 9, 23, 0))
        self.assertEqual(switch, utc(2026, 10, 12, 1, 0))
        self.assertEqual(target, "PEAK")

    def test_brute_force_against_reference(self):
        start = utc(2026, 9, 18, 0, 0)
        query_minutes = 18 * 24 * 60
        flips = scan_flips(start, query_minutes + 16 * 24 * 60)
        flip_index = 0
        for i in range(query_minutes):
            now = start + datetime.timedelta(minutes=i)
            while flips[flip_index] <= now:
                flip_index += 1
            switch, target = offpeak_clock.next_switch(now)
            self.assertEqual(switch, flips[flip_index], msg=str(now))
            self.assertEqual(target, "PEAK" if ref_is_peak(switch) else "OFF-PEAK",
                             msg=str(now))

    def test_brute_force_spring_festival(self):
        start = utc(2026, 2, 12, 0, 0)
        query_minutes = 14 * 24 * 60
        flips = scan_flips(start, query_minutes + 16 * 24 * 60)
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
        start = utc(2026, 9, 18, 0, 0)
        flips = scan_flips(start, 14 * 24 * 60)
        self.assertTrue(flips)
        for flip in flips:
            self.assertIn(flip.hour, (1, 4, 6, 10), msg=str(flip))
            self.assertEqual(flip.minute, 0, msg=str(flip))
            self.assertLess(flip.weekday(), 5, msg=str(flip))
            self.assertNotIn(flip.date(), CN_HOLIDAYS_2026, msg=str(flip))


class TestUserHolidays(unittest.TestCase):
    def test_extra_holiday_marks_off_peak(self):
        day = datetime.date(2027, 2, 16)
        with mock.patch.object(offpeak_clock, "USER_HOLIDAYS", {day}):
            self.assertFalse(offpeak_clock.is_peak(utc(2027, 2, 16, 2, 0)))
            self.assertTrue(offpeak_clock.is_peak(utc(2027, 2, 17, 2, 0)))

    def test_unknown_year_falls_back_to_weekday_rule(self):
        self.assertTrue(offpeak_clock.is_peak(utc(2027, 2, 16, 2, 0)))

    def test_embedded_2026_matches_notice(self):
        embedded = offpeak_clock.CN_HOLIDAYS[2026]
        self.assertEqual(embedded, frozenset(CN_HOLIDAYS_2026))


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
        cfg = self._load(json.dumps({
            "pos": ["a", "b"],
            "topmost": "yes",
            "holidays": "2026-01-01",
            "extra": 1,
        }))
        self.assertNotIn("pos", cfg)
        self.assertNotIn("topmost", cfg)
        self.assertNotIn("holidays", cfg)
        self.assertEqual(cfg.get("extra"), 1)

    def test_legacy_keys_stripped(self):
        cfg = self._load(json.dumps({
            "pos": [1, 2],
            "topmost": False,
            "holidays_off": True,
            "holiday_rules": {},
        }))
        self.assertEqual(cfg, {"pos": [1, 2], "topmost": False})

    def test_holidays_cleaned_and_sorted(self):
        cfg = self._load(json.dumps({
            "holidays": ["2027-10-01", "not-a-date", 5, "2026-01-01",
                         "2027-10-01", " 2027-01-01 "],
        }))
        self.assertEqual(cfg.get("holidays"),
                         ["2026-01-01", "2027-01-01", "2027-10-01"])

    def test_empty_holidays_dropped(self):
        cfg = self._load(json.dumps({"holidays": [], "topmost": True}))
        self.assertEqual(cfg, {"topmost": True})


if __name__ == "__main__":
    unittest.main()
