import tempfile
import unittest
from pathlib import Path

from PIL import Image

from merge_png_to_pdf import merge_missing_pdf


class MergeMissingPdfTests(unittest.TestCase):
    def test_merges_existing_capture_pages_into_named_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_dir = Path(temp_dir) / "MTH201_2023-24_F"
            capture_dir.mkdir()
            Image.new("RGB", (20, 30), "white").save(capture_dir / "pdf_page_1.png")
            Image.new("RGB", (20, 30), "black").save(capture_dir / "pdf_page_2.png")

            output = merge_missing_pdf(str(capture_dir))

            expected = capture_dir / "MTH201_2023-24_F.pdf"
            self.assertEqual(Path(output), expected)
            self.assertTrue(expected.read_bytes().startswith(b"%PDF-"))

    def test_returns_none_when_capture_directory_has_no_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_dir = Path(temp_dir) / "empty"
            capture_dir.mkdir()

            self.assertIsNone(merge_missing_pdf(str(capture_dir)))

    def test_does_not_overwrite_existing_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_dir = Path(temp_dir) / "MTH201_2023-24_F"
            capture_dir.mkdir()
            Image.new("RGB", (20, 30), "white").save(capture_dir / "pdf_page_1.png")
            existing_pdf = capture_dir / "MTH201_2023-24_F.pdf"
            existing_pdf.write_bytes(b"existing-pdf")

            output = merge_missing_pdf(str(capture_dir))

            self.assertEqual(Path(output), existing_pdf)
            self.assertEqual(existing_pdf.read_bytes(), b"existing-pdf")


if __name__ == "__main__":
    unittest.main()
