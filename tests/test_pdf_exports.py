import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import card_pdf


class CardPdfPhotoPrefetchTests(unittest.TestCase):
    def test_prefetches_unique_remote_photos_in_parallel_and_reuses_payload(self):
        trips = [
            {
                "images": [
                    {"file_name": "one.jpg", "url": "https://example.test/one.jpg"},
                    {"file_name": "one-copy.jpg", "url": "https://example.test/one.jpg"},
                    {"file_name": "two.jpg", "url": "https://example.test/two.jpg"},
                ]
            }
        ]

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def read(self, _):
                return self.payload

        calls = []
        active_downloads = 0
        max_active_downloads = 0
        lock = threading.Lock()

        def delayed_urlopen(request, timeout):
            nonlocal active_downloads, max_active_downloads
            calls.append((request.full_url, timeout))
            with lock:
                active_downloads += 1
                max_active_downloads = max(max_active_downloads, active_downloads)
            time.sleep(0.08)
            with lock:
                active_downloads -= 1
            return Response(request.full_url.encode())

        with tempfile.TemporaryDirectory() as directory:
            with patch("card_pdf.urllib.request.urlopen", side_effect=delayed_urlopen):
                card_pdf._prefetch_remote_photos(trips, Path(directory))

        self.assertEqual(max_active_downloads, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(trips[0]["images"][0]["_pdf_payload"], b"https://example.test/one.jpg")
        self.assertEqual(trips[0]["images"][1]["_pdf_payload"], b"https://example.test/one.jpg")
        self.assertEqual(trips[0]["images"][2]["_pdf_payload"], b"https://example.test/two.jpg")

    def test_read_photo_does_not_retry_failed_prefetch(self):
        image = {"url": "https://example.test/missing.jpg", "_pdf_payload": None}
        with patch("card_pdf.urllib.request.urlopen") as urlopen:
            payload = card_pdf._read_photo(image, Path("/tmp/does-not-exist"))
        self.assertIsNone(payload)
        urlopen.assert_not_called()


class PdfExportUiTests(unittest.TestCase):
    def test_both_export_buttons_target_pdf_routes_and_share_status_flow(self):
        template = (Path(__file__).parents[1] / "templates" / "index.html").read_text()
        self.assertIn("url_for('export_monthly_pdf'", template)
        self.assertIn("url_for('export_monthly_cards_pdf'", template)
        self.assertIn("document.querySelectorAll('.export-btn')", template)
        self.assertIn("กำลังสร้าง PDF", template)
        self.assertIn("ดาวน์โหลดเรียบร้อย", template)


if __name__ == "__main__":
    unittest.main()
