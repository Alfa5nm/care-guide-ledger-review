import unittest

from app.invoice import clean_field, records
from app.process import Section, positioned_rows


class LayoutTests(unittest.TestCase):
    def test_date_order_with_competing_valid_interpretations_abstains(self):
        cases = {"13/04/2026": "2026-04-13", "04-13-2026": "2026-04-13",
                 "05/04/2026": None, "31/02/2026": None}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(clean_field("invoice_date", value), expected)

    def test_spatial_columns_and_multi_page_evidence(self):
        words = [
            (x, y, x + len(token) * 5, y + 8, token)
            for y, columns in ((20, [(15, "Qty"), (65, "Amount"), (135, "Unit"), (157, "Price"), (225, "Description")]),
                               (40, [(15, "3"), (65, "21"), (135, "7"), (225, "Cable")]))
            for x, token in columns
        ]
        sections = [
            Section("Page 1", "Invoice number: DEV-02\nSupplier: Example Supplier"),
            Section("Page 2", "Total: 21", positioned=list(positioned_rows(words))),
        ]
        record, = records(sections)
        self.assertEqual(record["data"]["line_items"], [
            {"description": "Cable", "quantity": "3", "unit_price": "7", "amount": "21"},
        ])
        self.assertEqual(record["evidence"]["_pages"]["total"], 2)
        sections[1].positioned = sections[1].positioned[1:]
        record, = records(sections)
        self.assertEqual(record["data"]["line_items"], [])
