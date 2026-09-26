import unittest
from unittest.mock import patch
import base64

from capture_canvas import parse_exam_metadata, parse_metadata_from_text


class FakePdfPage:
    def __init__(self, layer_text="", pdf_text=""):
        self.layer_text = layer_text
        self.pdf_text = pdf_text

    def evaluate(self, script):
        if "getTextContent" in script:
            return self.pdf_text
        if "toDataURL" in script:
            return base64.b64encode(b"png bytes").decode("ascii")
        return self.layer_text


class ParseExamMetadataTests(unittest.TestCase):
    def test_parses_academic_year_before_semester_and_final_label(self):
        text = "MTH201-2024/25-1st Semester-Final Examination"

        self.assertEqual(
            parse_metadata_from_text(text),
            ("MTH201", "2024-25", "F"),
        )

    def test_parses_academic_year_before_semester_and_resit_label(self):
        text = "MTH201-2024/25-1st Semester-Resit Examination"

        self.assertEqual(
            parse_metadata_from_text(text),
            ("MTH201", "2024-25", "R"),
        )

    def test_does_not_treat_an_exam_date_as_an_academic_year(self):
        text = "MTH201 Final Examination held on 12/05/2025"

        self.assertEqual(
            parse_metadata_from_text(text),
            ("MTH201", "unknown", "F"),
        )

    def test_parses_hyphenated_year_from_paper_code(self):
        text = "PAPER CODE: EEE201/24-25/S1/Final Exam"

        self.assertEqual(
            parse_metadata_from_text(text),
            ("EEE201", "2024-25", "F"),
        )

    def test_parses_course_code_with_letter_suffix(self):
        text = "MTH102TC 2nd SEMESTER 2024/25 RESIT EXAMINATION"

        self.assertEqual(
            parse_metadata_from_text(text),
            ("MTH102TC", "2024-25", "R"),
        )

    def test_does_not_read_are_sitting_as_resit(self):
        text = "MTH102 2nd SEMESTER 2024/25 FINAL EXAMINATION Make sure that you are sitting"

        self.assertEqual(
            parse_metadata_from_text(text),
            ("MTH102", "2024-25", "F"),
        )

    def test_reads_pdf_document_when_text_layer_is_empty(self):
        page = FakePdfPage(pdf_text="EEE201 Resit Exam, Semester 1, 2024/2025")

        self.assertEqual(parse_exam_metadata(page), ("EEE201", "2024-25", "R"))

    def test_uses_ocr_when_pdf_has_no_extractable_text(self):
        page = FakePdfPage()
        cover_text = "EEE201 Resit Exam, Semester 1, 2024/2025"

        with patch("capture_canvas._ocr_image_text", return_value=cover_text, create=True):
            self.assertEqual(parse_exam_metadata(page), ("EEE201", "2024-25", "R"))


if __name__ == "__main__":
    unittest.main()
