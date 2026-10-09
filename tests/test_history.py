import os
import tempfile
import unittest

from carscraper.history import price_history, record_run
from carscraper.models import Car


def car(price, listing_id="abc", source="cars_com"):
    return Car(source=source, listing_id=listing_id, title="2023 VW Tiguan",
               url="https://example.com/abc", price=price)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "h.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_marks_listing_new(self):
        r = record_run([car(30000)], self.db)
        self.assertEqual(len(r.new), 1)
        self.assertEqual(r.drops, [])

    def test_unchanged_price_reports_nothing_and_adds_no_row(self):
        record_run([car(30000)], self.db)
        r = record_run([car(30000)], self.db)
        self.assertEqual((r.new, r.drops, r.increases), ([], [], []))
        self.assertEqual(len(price_history(self.db, "cars_com:abc")), 1)

    def test_price_drop_detected(self):
        record_run([car(30000)], self.db)
        r = record_run([car(28500)], self.db)
        self.assertEqual(len(r.drops), 1)
        self.assertEqual(r.drops[0].delta, -1500)
        self.assertEqual(len(price_history(self.db, "cars_com:abc")), 2)

    def test_price_increase_detected(self):
        record_run([car(30000)], self.db)
        r = record_run([car(31000)], self.db)
        self.assertEqual(len(r.increases), 1)
        self.assertEqual(r.drops, [])

    def test_same_id_on_different_sources_is_separate(self):
        record_run([car(30000, source="cars_com"), car(25000, source="craigslist")], self.db)
        r = record_run([car(29000, source="cars_com"), car(25000, source="craigslist")], self.db)
        self.assertEqual(len(r.drops), 1)

    def test_listing_without_price_is_skipped(self):
        r = record_run([car(None)], self.db)
        self.assertEqual(r.new, [])


if __name__ == "__main__":
    unittest.main()
