import unittest

from trip_batch import build_trip_batch, parse_round_count


class ParseRoundCountTests(unittest.TestCase):
    def test_defaults_to_one_round(self):
        self.assertEqual(parse_round_count(None), 1)
        self.assertEqual(parse_round_count(""), 1)

    def test_accepts_one_to_one_hundred_rounds(self):
        self.assertEqual(parse_round_count("1"), 1)
        self.assertEqual(parse_round_count("100"), 100)

    def test_rejects_invalid_round_counts(self):
        for value in ("0", "101", "1.5", "abc"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "จำนวนรอบ"):
                    parse_round_count(value)


class BuildTripBatchTests(unittest.TestCase):
    def setUp(self):
        self.base_trip = {
            "trip_date": "2026-10-08",
            "origin": "เอ",
            "destination": "บี",
            "vehicle_type": "6 ล้อ",
            "toll_fee": 215,
            "note": "สินค้าแช่เย็น",
            "owner": "งาน มิตซูบิชิ",
        }

    def test_single_round_adds_round_note(self):
        rows = build_trip_batch(self.base_trip, round_count=1, return_pickup=False)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "เอ")
        self.assertEqual(rows[0]["destination"], "บี")
        self.assertEqual(rows[0]["note"], "สินค้าแช่เย็น · รอบ 1")

    def test_five_rounds_create_five_numbered_outbound_rows(self):
        rows = build_trip_batch(self.base_trip, round_count=5, return_pickup=False)

        self.assertEqual(len(rows), 5)
        self.assertEqual(
            [row["note"] for row in rows],
            [f"สินค้าแช่เย็น · รอบ {round_number}" for round_number in range(1, 6)],
        )

    def test_return_pickup_adds_reversed_row_for_each_round(self):
        rows = build_trip_batch(self.base_trip, round_count=2, return_pickup=True)

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(row["origin"], row["destination"], row["note"]) for row in rows],
            [
                ("เอ", "บี", "สินค้าแช่เย็น · รอบ 1"),
                ("บี", "เอ", "สินค้าแช่เย็น · รอบ 1 · รับกลับ"),
                ("เอ", "บี", "สินค้าแช่เย็น · รอบ 2"),
                ("บี", "เอ", "สินค้าแช่เย็น · รอบ 2 · รับกลับ"),
            ],
        )

    def test_empty_note_does_not_add_a_leading_separator(self):
        self.base_trip["note"] = ""

        rows = build_trip_batch(self.base_trip, round_count=1, return_pickup=True)

        self.assertEqual(rows[0]["note"], "รอบ 1")
        self.assertEqual(rows[1]["note"], "รอบ 1 · รับกลับ")


if __name__ == "__main__":
    unittest.main()
