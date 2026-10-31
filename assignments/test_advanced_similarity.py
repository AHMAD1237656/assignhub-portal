
"""
AssignHub - Advanced Similarity Test Suite.

Run:
python manage.py test assignments.test_advanced_similarity -v 2
"""

import io

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile

from .forms import validate_submission_document
from .models import Assignment, Submission

from .similarity import (
    Extracted,
    MAX_FILE_BYTES,
    _chunks,
    _image_from_bytes,
    analyze_submission,
    extract_file,
    lexical_score,
    matching_passages,
    normalize,
    shingles,
    submission_text,
    tokens,
)


TEXT_A = (
    "Universities provide opportunities for "
    "students to explore academic research "
    "through projects laboratory activities "
    "digital libraries and scholarly "
    "publications that support critical "
    "thinking and meaningful learning outcomes."
)

TEXT_B = (
    "Farmers investigate seasonal rainfall "
    "patterns and irrigation methods in "
    "order to improve agricultural production "
    "and maintain fertile soil during periods "
    "of rapidly changing weather conditions "
    "and climate variability."
)


# ==========================================
# TEST GROUP 1 - SIMILARITY ALGORITHMS
# ==========================================

class TextSimilarityTests(SimpleTestCase):

    def test_01_casefold(self):
        self.assertEqual(
            normalize("HELLO World"),
            "hello world",
        )

    def test_02_spaces(self):
        self.assertEqual(
            normalize(" A\n B\t  C "),
            "a b c",
        )

    def test_03_punctuation(self):
        self.assertEqual(
            normalize("Hello, world!"),
            "hello world",
        )

    def test_04_unicode(self):
        self.assertEqual(
            normalize("ＡＢＣ"),
            "abc",
        )

    def test_05_non_string(self):
        self.assertEqual(
            normalize(None),
            "",
        )

    def test_06_tokens(self):
        self.assertEqual(
            tokens("One, TWO"),
            ["one", "two"],
        )

    def test_07_exact_shingles(self):
        self.assertEqual(
            len(
                shingles(
                    ["a", "b", "c", "d", "e", "f"]
                )
            ),
            2,
        )

    def test_08_short_shingles(self):
        self.assertEqual(
            shingles(["a", "b"]),
            set(),
        )

    def test_09_identical(self):
        self.assertEqual(
            lexical_score(TEXT_A, TEXT_A),
            100,
        )

    def test_10_case_invariant(self):
        self.assertEqual(
            lexical_score(
                TEXT_A,
                TEXT_A.upper(),
            ),
            100,
        )

    def test_11_punctuation_invariant(self):
        self.assertEqual(
            lexical_score(
                TEXT_A,
                TEXT_A.replace(" ", ", "),
            ),
            100,
        )

    def test_12_unrelated(self):
        self.assertEqual(
            lexical_score(
                TEXT_A,
                TEXT_B,
            ),
            0,
        )

    def test_13_no_short_answer_false_positive(self):
        self.assertEqual(
            lexical_score(
                "one two",
                "one two",
            ),
            0,
        )

    def test_14_partial_copy(self):
        copied = (
            " ".join(TEXT_A.split()[:11])
            + " "
            + TEXT_B
        )

        self.assertGreater(
            lexical_score(TEXT_A, copied),
            0,
        )

    def test_15_source_coverage_directional(self):
        self.assertEqual(
            lexical_score(
                TEXT_A,
                TEXT_A + " " + TEXT_B,
            ),
            100,
        )

        self.assertLess(
            lexical_score(
                TEXT_A + " " + TEXT_B,
                TEXT_A,
            ),
            100,
        )

    def test_16_matched_passages(self):
        self.assertTrue(
            matching_passages(
                TEXT_A,
                TEXT_A,
            )
        )

    def test_17_unrelated_passages(self):
        self.assertEqual(
            matching_passages(
                TEXT_A,
                TEXT_B,
            ),
            [],
        )

    def test_18_passage_limit(self):
        self.assertLessEqual(
            len(
                matching_passages(
                    TEXT_A,
                    TEXT_A,
                )
            ),
            5,
        )

    def test_19_unicode_words(self):
        self.assertEqual(
            tokens("سلام دنیا"),
            ["سلام", "دنیا"],
        )

    def test_20_chunk_limit(self):
        self.assertLessEqual(
            len(
                _chunks(
                    "word " * 3000
                )
            ),
            15,
        )

    def test_21_empty_chunks(self):
        self.assertEqual(
            _chunks(""),
            [],
        )


# ==========================================
# TEST GROUP 2 - UPLOAD VALIDATION
# ==========================================

class UploadValidationTests(SimpleTestCase):

    @staticmethod
    def image_upload(extension="png"):
        from PIL import Image

        image = Image.new(
            "RGB",
            (80, 40),
            "white",
        )

        content = io.BytesIO()

        image.save(
            content,
            format={
                "png": "PNG",
                "jpg": "JPEG",
                "webp": "WEBP",
            }[extension],
        )

        return SimpleUploadedFile(
            f"photo.{extension}",
            content.getvalue(),
        )

    def test_22_pdf_accepted(self):
        upload = SimpleUploadedFile(
            "scan.pdf",
            b"%PDF-1.4\nexample",
        )

        self.assertIs(
            validate_submission_document(upload),
            upload,
        )

    def test_23_png_accepted(self):
        upload = self.image_upload("png")

        self.assertIs(
            validate_submission_document(upload),
            upload,
        )

    def test_24_jpg_accepted(self):
        upload = self.image_upload("jpg")

        self.assertIs(
            validate_submission_document(upload),
            upload,
        )

    def test_25_webp_accepted(self):
        upload = self.image_upload("webp")

        self.assertIs(
            validate_submission_document(upload),
            upload,
        )

    def test_26_fake_png_rejected(self):
        with self.assertRaises(
            ValidationError
        ):
            validate_submission_document(
                SimpleUploadedFile(
                    "photo.png",
                    b"not an image",
                )
            )

    def test_27_executable_rejected(self):
        with self.assertRaises(
            ValidationError
        ):
            validate_submission_document(
                SimpleUploadedFile(
                    "cmd.exe",
                    b"EXE",
                )
            )

    def test_28_bad_pdf_header_rejected(self):
        with self.assertRaises(
            ValidationError
        ):
            validate_submission_document(
                SimpleUploadedFile(
                    "file.pdf",
                    b"not a pdf",
                )
            )

    def test_29_large_upload_rejected(self):
        with self.assertRaises(
            ValidationError
        ):
            validate_submission_document(
                SimpleUploadedFile(
                    "file.pdf",
                    b"%PDF-"
                    + b"a" * MAX_FILE_BYTES,
                )
            )

    def test_30_empty_upload_rejected(self):
        with self.assertRaises(
            ValidationError
        ):
            validate_submission_document(
                SimpleUploadedFile(
                    "file.pdf",
                    b"",
                )
            )

    def test_31_image_stream_position_restored(self):
        upload = self.image_upload()

        upload.seek(3)

        validate_submission_document(upload)

        self.assertEqual(
            upload.tell(),
            3,
        )

    def test_32_reject_oversized_image_dimensions(self):
        from PIL import Image

        with patch(
            "assignments.similarity.MAX_PIXELS",
            200,
        ):

            data = io.BytesIO()

            Image.new(
                "RGB",
                (20, 20),
                "white",
            ).save(
                data,
                format="PNG",
            )

            with self.assertRaises(
                ValueError
            ):
                _image_from_bytes(
                    data.getvalue()
                )


# ==========================================
# TEST GROUP 3 - OCR PIPELINE
# ==========================================

class OcrPipelineTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def test_33_scanned_image_dispatch(self):
        upload = SimpleUploadedFile(
            "scan.png",
            b"placeholder",
        )

        pages = (
            [
                (
                    1,
                    TEXT_A,
                    91.0,
                    ["tesseract"],
                    [],
                )
            ],
            1,
        )

        with patch(
            "assignments.similarity._document_pages",
            return_value=pages,
        ) as mocked:

            result = extract_file(
                upload
            )

        self.assertEqual(
            result.status,
            "ready",
        )

        self.assertEqual(
            result.pages,
            1,
        )

        self.assertEqual(
            result.confidence,
            91.0,
        )

        self.assertEqual(
            mocked.call_args.args[1],
            ".png",
        )

    def test_34_image_unreadable_not_zero(self):
        upload = SimpleUploadedFile(
            "scan.png",
            b"placeholder",
        )

        pages = (
            [
                (
                    1,
                    "",
                    None,
                    [],
                    ["No OCR available"],
                )
            ],
            1,
        )

        with patch(
            "assignments.similarity._document_pages",
            return_value=pages,
        ):

            result = extract_file(
                upload
            )

        self.assertEqual(
            result.status,
            "unreadable",
        )

        self.assertTrue(
            result.warnings
        )

    def test_35_mixed_pdf_partial(self):
        upload = SimpleUploadedFile(
            "mixed.pdf",
            b"%PDF-fake",
        )

        pages = [
            (
                1,
                TEXT_A,
                None,
                ["pdf-text"],
                [],
            ),
            (
                2,
                "",
                11.0,
                ["tesseract"],
                ["poor scan"],
            ),
        ]

        with patch(
            "assignments.similarity._document_pages",
            return_value=(
                pages,
                2,
            ),
        ):

            result = extract_file(
                upload
            )

        self.assertEqual(
            result.status,
            "partial",
        )

        self.assertEqual(
            result.pages,
            1,
        )

        self.assertEqual(
            result.total_pages,
            2,
        )

    def test_36_ocr_cache_hits(self):
        upload = SimpleUploadedFile(
            "scan.png",
            b"placeholder",
        )

        pages = (
            [
                (
                    1,
                    TEXT_A,
                    81,
                    ["tesseract"],
                    [],
                )
            ],
            1,
        )

        with patch(
            "assignments.similarity._document_pages",
            return_value=pages,
        ) as mocked:

            extract_file(upload)

            extract_file(
                SimpleUploadedFile(
                    "scan.png",
                    b"placeholder",
                )
            )

        self.assertEqual(
            mocked.call_count,
            1,
        )

    def test_37_cache_is_content_specific(self):
        first = SimpleUploadedFile(
            "scan.png",
            b"aaa",
        )

        second = SimpleUploadedFile(
            "scan.png",
            b"bbb",
        )

        pages = (
            [
                (
                    1,
                    TEXT_A,
                    81,
                    ["tesseract"],
                    [],
                )
            ],
            1,
        )

        with patch(
            "assignments.similarity._document_pages",
            return_value=pages,
        ) as mocked:

            extract_file(first)
            extract_file(second)

        self.assertEqual(
            mocked.call_count,
            2,
        )

    def test_38_invalid_ocr_mode(self):
        with self.assertRaises(
            ValidationError
        ):
            extract_file(
                SimpleUploadedFile(
                    "scan.png",
                    b"a",
                ),
                "random",
            )

    def test_39_unsupported_extension(self):
        result = extract_file(
            SimpleUploadedFile(
                "scan.zip",
                b"a",
            )
        )

        self.assertEqual(
            result.status,
            "unsupported",
        )

    def test_40_corrupt_document(self):
        upload = SimpleUploadedFile(
            "scan.png",
            b"placeholder",
        )

        with patch(
            "assignments.similarity._document_pages",
            side_effect=ValueError(
                "Corrupt image"
            ),
        ):

            result = extract_file(
                upload
            )

        self.assertEqual(
            result.status,
            "unsupported",
        )

    def test_41_pure_text_is_ready(self):
        submission = SimpleNamespace(
            text_content=TEXT_A,
            submission_file=None,
        )

        self.assertEqual(
            submission_text(
                submission
            ).status,
            "ready",
        )

    def test_42_short_text_unreadable(self):
        submission = SimpleNamespace(
            text_content="Hi",
            submission_file=None,
        )

        self.assertEqual(
            submission_text(
                submission
            ).status,
            "unreadable",
        )

    def test_43_file_error_preserves_typed_text(self):
        submission = SimpleNamespace(
            text_content=TEXT_A,
            submission_file="mock",
        )

        with patch(
            "assignments.similarity.extract_file",
            return_value=Extracted(
                status="unsupported",
                warnings=["Invalid scan"],
            ),
        ):

            result = submission_text(
                submission
            )

        self.assertEqual(
            result.status,
            "partial",
        )

        self.assertIn(
            "Invalid scan",
            result.warnings,
        )

    def test_44_handwritten_mode_delegated(self):
        upload = SimpleUploadedFile(
            "scan.png",
            b"somebytes",
        )

        pages = (
            [
                (
                    1,
                    TEXT_A,
                    None,
                    ["trocr"],
                    [],
                )
            ],
            1,
        )

        with patch(
            "assignments.similarity._document_pages",
            return_value=pages,
        ) as mocked:

            result = extract_file(
                upload,
                "handwritten",
            )

        self.assertIn(
            "trocr",
            result.methods,
        )

        self.assertEqual(
            mocked.call_args.args[2],
            "handwritten",
        )


# ==========================================
# TEST GROUP 4 - DJANGO INTEGRATION
# ==========================================

class SubmissionReportTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.teacher = User.objects.create_user(
            username="adv_teacher",
            password="TestPass123!",
        )

        cls.other_teacher = User.objects.create_user(
            username="adv_other_teacher",
            password="TestPass123!",
        )

        cls.student_a = User.objects.create_user(
            username="adv_student_a",
            password="TestPass123!",
        )

        cls.student_b = User.objects.create_user(
            username="adv_student_b",
            password="TestPass123!",
        )

        cls.student_c = User.objects.create_user(
            username="adv_student_c",
            password="TestPass123!",
        )

        users = [
            (
                cls.teacher,
                UserProfile.Role.TEACHER,
            ),
            (
                cls.other_teacher,
                UserProfile.Role.TEACHER,
            ),
            (
                cls.student_a,
                UserProfile.Role.STUDENT,
            ),
            (
                cls.student_b,
                UserProfile.Role.STUDENT,
            ),
            (
                cls.student_c,
                UserProfile.Role.STUDENT,
            ),
        ]

        for user, role in users:
            UserProfile.objects.create(
                user=user,
                role=role,
            )

        cls.assignment = Assignment.objects.create(
            created_by=cls.teacher,
            title="OCR A",
            instructions="Answer",
            status=Assignment.Status.DRAFT,
            deadline=(
                timezone.now()
                + timedelta(days=4)
            ),
            total_marks=100,
        )

        cls.other_assignment = Assignment.objects.create(
            created_by=cls.teacher,
            title="OCR B",
            instructions="Answer",
            status=Assignment.Status.DRAFT,
            deadline=(
                timezone.now()
                + timedelta(days=4)
            ),
            total_marks=100,
        )

        cls.first = Submission.objects.create(
            student=cls.student_a,
            assignment=cls.assignment,
            status=Submission.Status.SUBMITTED,
            submitted_at=timezone.now(),
            text_content=TEXT_A,
        )

        cls.second = Submission.objects.create(
            student=cls.student_b,
            assignment=cls.assignment,
            status=Submission.Status.GRADED,
            submitted_at=timezone.now(),
            text_content=TEXT_A,
            marks=87,
            feedback="Preserved feedback",
        )

        cls.foreign = Submission.objects.create(
            student=cls.student_c,
            assignment=cls.other_assignment,
            status=Submission.Status.SUBMITTED,
            submitted_at=timezone.now(),
            text_content=TEXT_A,
        )

    def url(self):
        return reverse(
            "assignments:submission_similarity",
            args=[self.first.pk],
        )

    def test_45_identical_submissions_match(self):
        report = analyze_submission(
            self.first
        )

        self.assertEqual(
            report["highest_score"],
            100,
        )

        self.assertEqual(
            report["checked"],
            1,
        )

    def test_46_no_self_compare(self):
        report = analyze_submission(
            self.first
        )

        ids = [
            match.submission.pk
            for match in report["matches"]
        ]

        self.assertNotIn(
            self.first.pk,
            ids,
        )

    def test_47_cross_assignment_excluded(self):
        report = analyze_submission(
            self.first
        )

        ids = [
            match.submission.pk
            for match in report["matches"]
        ]

        self.assertNotIn(
            self.foreign.pk,
            ids,
        )

    def test_48_graded_candidate_eligible(self):
        report = analyze_submission(
            self.first
        )

        ids = [
            match.submission.pk
            for match in report["matches"]
        ]

        self.assertIn(
            self.second.pk,
            ids,
        )

    def test_49_draft_candidate_excluded(self):
        self.second.status = (
            Submission.Status.DRAFT
        )

        self.second.save(
            update_fields=["status"]
        )

        report = analyze_submission(
            self.first
        )

        self.assertEqual(
            report["checked"],
            0,
        )

    def test_50_draft_source_denied(self):
        self.first.status = (
            Submission.Status.DRAFT
        )

        with self.assertRaises(
            ValidationError
        ):
            analyze_submission(
                self.first
            )

    def test_51_no_candidate_not_zero(self):
        self.second.status = (
            Submission.Status.DRAFT
        )

        self.second.save(
            update_fields=["status"]
        )

        report = analyze_submission(
            self.first
        )

        self.assertIsNone(
            report["highest_score"]
        )

    def test_52_teacher_get(self):
        self.client.force_login(
            self.teacher
        )

        response = self.client.get(
            self.url()
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_53_teacher_post(self):
        self.client.force_login(
            self.teacher
        )

        response = self.client.post(
            self.url(),
            {"ocr_mode": "auto"},
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["report"][
                "highest_score"
            ],
            100,
        )

    def test_54_student_forbidden(self):
        self.client.force_login(
            self.student_a
        )

        response = self.client.post(
            self.url()
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_55_other_teacher_forbidden(self):
        self.client.force_login(
            self.other_teacher
        )

        response = self.client.get(
            self.url()
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_56_anonymous_redirect(self):
        response = self.client.get(
            self.url()
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_57_get_does_not_analyze(self):
        self.client.force_login(
            self.teacher
        )

        with patch(
            "assignments.views.analyze_submission"
        ) as mocked:

            self.client.get(
                self.url()
            )

        mocked.assert_not_called()

    def test_58_invalid_mode_rejected(self):
        self.client.force_login(
            self.teacher
        )

        with patch(
            "assignments.views.analyze_submission"
        ) as mocked:

            response = self.client.post(
                self.url(),
                {
                    "ocr_mode": "invalid"
                },
            )

        mocked.assert_not_called()

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "Invalid OCR mode",
        )

    def test_59_grade_not_changed(self):
        self.client.force_login(
            self.teacher
        )

        self.client.post(
            self.url()
        )

        self.second.refresh_from_db()

        self.assertEqual(
            self.second.marks,
            87,
        )

        self.assertEqual(
            self.second.feedback,
            "Preserved feedback",
        )

    def test_60_no_untrusted_html(self):
        self.second.text_content = (
            TEXT_A
            + " <script>alert('x')</script>"
        )

        self.second.save(
            update_fields=["text_content"]
        )

        self.client.force_login(
            self.teacher
        )

        response = self.client.post(
            self.url()
        )

        self.assertNotContains(
            response,
            "<script>alert('x')</script>",
        )

    def test_61_csrf_required(self):
        client = Client(
            enforce_csrf_checks=True
        )

        client.force_login(
            self.teacher
        )

        response = client.post(
            self.url()
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_62_source_low_quality_not_zero(self):
        self.first.text_content = "Hi"

        self.first.save(
            update_fields=["text_content"]
        )

        report = analyze_submission(
            self.first
        )

        self.assertIsNone(
            report["highest_score"]
        )

    def test_63_ocr_unreadable_candidate_skipped(self):
        self.second.text_content = ""

        self.second.submission_file.name = (
            "unreadable.pdf"
        )

        self.second.save(
            update_fields=[
                "text_content",
                "submission_file",
            ]
        )

        with patch(
            "assignments.similarity.extract_file",
            return_value=Extracted(
                status="unreadable",
                warnings=[
                    "No text"
                ],
            ),
        ):

            report = analyze_submission(
                self.first
            )

        self.assertEqual(
            report["checked"],
            0,
        )

        self.assertEqual(
            len(report["skipped"]),
            1,
        )

    def test_64_semantic_off_by_default(self):
        report = analyze_submission(
            self.first
        )

        self.assertFalse(
            report["semantic_enabled"]
        )

    def test_65_semantic_missing_falls_back(self):
        with patch(
            "assignments.similarity._semantic_model",
            side_effect=ImportError,
        ):

            report = analyze_submission(
                self.first,
                use_semantic=True,
            )

        self.assertFalse(
            report["semantic_enabled"]
        )

        self.assertEqual(
            report["highest_score"],
            100,
        )

    def test_66_semantic_mocked_score(self):
        with patch(
            "assignments.similarity._semantic_model"
        ):

            with patch(
                "assignments.similarity.semantic_score",
                return_value=94.0,
            ):

                report = analyze_submission(
                    self.first,
                    use_semantic=True,
                )

        self.assertTrue(
            report["semantic_enabled"]
        )

        self.assertEqual(
            report["matches"][0].semantic,
            94.0,
        )

    def test_67_scanned_pdf_comparison(self):
        self.first.text_content = ""

        self.first.submission_file.name = (
            "scan.pdf"
        )

        self.first.save(
            update_fields=[
                "text_content",
                "submission_file",
            ]
        )

        fake_ocr = Extracted(
            text=TEXT_A,
            status="ready",
            pages=1,
            total_pages=1,
            methods=["tesseract"],
        )

        with patch(
            "assignments.similarity.extract_file",
            return_value=fake_ocr,
        ):

            report = analyze_submission(
                self.first
            )

        self.assertEqual(
            report["checked"],
            1,
        )

        self.assertEqual(
            report["highest_score"],
            100,
        )

    def test_68_request_mode_forwarded(self):
        self.client.force_login(
            self.teacher
        )

        fake_report = {
            "source": Extracted(
                status="unreadable"
            ),
            "matches": [],
            "warnings": [],
            "highest_score": None,
            "checked": 0,
            "skipped": [],
            "limited": False,
            "semantic_enabled": False,
        }

        with patch(
            "assignments.views.analyze_submission",
            return_value=fake_report,
        ) as mocked:

            response = self.client.post(
                self.url(),
                {
                    "ocr_mode": "handwritten",
                    "semantic": "on",
                },
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        mocked.assert_called_once_with(
            self.first,
            mode="handwritten",
            use_semantic=True,
        )
