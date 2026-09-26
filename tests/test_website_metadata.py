import unittest
from unittest.mock import patch

from capture_canvas import resolve_paper_metadata


class WebsiteMetadataTests(unittest.TestCase):
    def test_website_fields_win_over_conflicting_pdf_cover(self):
        with patch("capture_canvas.parse_exam_metadata") as parse_pdf:
            metadata = resolve_paper_metadata(
                "EEE201", "EEE201 | 2024/25 | Resit Examination", "",
                object(), "EEE201",
            )

        self.assertEqual(metadata, ("EEE201", "2024-25", "R"))
        parse_pdf.assert_not_called()

    def test_detail_page_fills_missing_search_fields(self):
        with patch("capture_canvas.parse_exam_metadata") as parse_pdf:
            metadata = resolve_paper_metadata(
                "EEE201", "EEE201", "Academic Year: 2024/25\nExam Type: Resit",
                object(), "EEE201",
            )

        self.assertEqual(metadata, ("EEE201", "2024-25", "R"))
        parse_pdf.assert_not_called()

    def test_pdf_fills_only_missing_fields(self):
        with patch("capture_canvas.parse_exam_metadata", return_value=("EEE201", "2023-24", "F")) as parse_pdf:
            metadata = resolve_paper_metadata(
                "EEE201", "EEE201 | Resit", "", object(), "EEE201",
            )

        self.assertEqual(metadata, ("EEE201", "2023-24", "R"))
        parse_pdf.assert_called_once()

    def test_ignores_other_course_in_detail_text(self):
        with patch("capture_canvas.parse_exam_metadata", return_value=("EEE201", "2024-25", "F")):
            metadata = resolve_paper_metadata(
                "EEE201", "EEE201", "MTH101 2022/23 Resit", object(), "EEE201",
            )

        self.assertEqual(metadata, ("EEE201", "2024-25", "F"))

    def test_ambiguous_site_type_falls_back_to_pdf(self):
        with patch("capture_canvas.parse_exam_metadata", return_value=("EEE201", "2024-25", "F")) as parse_pdf:
            metadata = resolve_paper_metadata(
                "EEE201", "EEE201 | 2024/25 | Final / Resit",
                "", object(), "EEE201",
            )

        self.assertEqual(metadata, ("EEE201", "2024-25", "F"))
        parse_pdf.assert_called_once()


if __name__ == "__main__":
    unittest.main()
