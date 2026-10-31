
"""AssignHub local OCR + similarity engine.

No paid API or remote inference.
Handwriting model and semantic model are optional.
Analysis does not change submissions or grades.
"""

import hashlib
import io
import re
import unicodedata

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Submission


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 12
MAX_PIXELS = 8_000_000
MAX_TEXT_CHARS = 60_000
MAX_COMPARE = 30
MAX_MATCHES = 15
MAX_LINES_PER_PAGE = 45

SHINGLE = 5
MIN_WORDS = 8
OCR_CACHE_SECONDS = 15 * 60

TROCR_MODEL = "microsoft/trocr-base-handwritten"

SEMANTIC_MODEL = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

FILE_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


# ==========================================
# RESULT DATA STRUCTURES
# ==========================================

@dataclass
class Extracted:
    text: str = ""
    status: str = "unreadable"
    pages: int = 0
    total_pages: int = 0
    confidence: float | None = None
    methods: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    page_details: list = field(default_factory=list)

    @property
    def usable(self):
        return (
            self.status in {"ready", "partial"}
            and len(tokens(self.text)) >= MIN_WORDS
        )


@dataclass
class Match:
    submission: object
    lexical: float
    semantic: float | None
    passages: list
    source_status: str
    candidate_status: str
    candidate_confidence: float | None


# ==========================================
# TEXT NORMALIZATION
# ==========================================

def normalize(text):
    if not isinstance(text, str):
        return ""

    text = unicodedata.normalize(
        "NFKC",
        text,
    ).casefold()

    return " ".join(
        re.findall(
            r"\w+",
            text,
            re.UNICODE,
        )
    )


def tokens(text):
    return normalize(text).split()


def shingles(words):
    return {
        tuple(
            words[i:i + SHINGLE]
        )
        for i in range(
            max(
                0,
                len(words) - SHINGLE + 1,
            )
        )
    }


def lexical_score(a, b):
    """
    Percentage of target document's
    five-word shingles appearing in candidate.

    Not a plagiarism probability.
    """

    a = tokens(a)
    b = tokens(b)

    if (
        len(a) < MIN_WORDS
        or len(b) < MIN_WORDS
    ):
        return 0.0

    x = shingles(a)
    y = shingles(b)

    if not x or not y:
        return 0.0

    overlap = len(x & y)

    return round(
        100 * overlap / len(x),
        2,
    )


# ==========================================
# MATCHING PASSAGES
# ==========================================

def matching_passages(a, b):
    x = tokens(a)[:1300]
    y = tokens(b)[:1300]

    if (
        len(x) < MIN_WORDS
        or len(y) < MIN_WORDS
    ):
        return []

    matcher = SequenceMatcher(
        None,
        x,
        y,
        autojunk=True,
    )

    result = []

    for block in matcher.get_matching_blocks():

        if block.size < SHINGLE:
            continue

        result.append({
            "text": " ".join(
                x[
                    block.a:
                    block.a + min(
                        block.size,
                        55,
                    )
                ]
            ),
            "words": block.size,
        })

    result.sort(
        key=lambda item: -item["words"]
    )

    return result[:5]


# ==========================================
# SAFE IMAGE LOADING
# ==========================================

def _image_from_bytes(content):
    from PIL import (
        Image,
        ImageOps,
        UnidentifiedImageError,
    )



    try:
        with Image.open(
            io.BytesIO(content)
        ) as img:

            if (
                img.width * img.height
                > MAX_PIXELS
            ):
                raise ValueError(
                    "Image resolution exceeds analysis limit."
                )

            image = ImageOps.exif_transpose(
                img
            ).convert("RGB")

            image.load()

            return image

    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
    ) as exc:

        raise ValueError(
            "Image is invalid or exceeds safety limits."
        ) from exc


def _prepare_image(image):
    """
    Grayscale, contrast and safe upscale
    before OCR.
    """

    from PIL import (
        ImageOps,
        ImageEnhance,
    )

    result = ImageOps.autocontrast(
        ImageOps.grayscale(image)
    )

    if result.width < 1000:

        scale = min(
            2,
            1000 / max(
                1,
                result.width,
            ),
        )

        if (
            result.width
            * result.height
            * scale
            * scale
            <= MAX_PIXELS
        ):
            result = result.resize(
                (
                    int(
                        result.width * scale
                    ),
                    int(
                        result.height * scale
                    ),
                )
            )

    return ImageEnhance.Contrast(
        result
    ).enhance(1.25).convert("RGB")


# ==========================================
# PRINTED / SCANNED TEXT OCR
# ==========================================

def _tesseract(image):
    """
    Returns:
        recognized text
        average confidence (0-100)
        recognized line bounding boxes
    """

    import os
    import pytesseract

    from pytesseract import Output

    from pytesseract.pytesseract import (
        TesseractNotFoundError,
    )

    command = os.getenv(
        "TESSERACT_CMD",
        "",
    ).strip()

    if command:
        pytesseract.pytesseract.tesseract_cmd = (
            command
        )

    try:
        data = pytesseract.image_to_data(
            image,
            lang=os.getenv(
                "ASSIGNHUB_OCR_LANG",
                "eng",
            ),
            config="--psm 6",
            output_type=Output.DICT,
            timeout=20,
        )

    except (
        TesseractNotFoundError,
        RuntimeError,
        OSError,
    ) as exc:

        raise RuntimeError(
            "Tesseract OCR unavailable or timed out."
        ) from exc

    lines = {}
    confidences = []

    n = len(
        data.get(
            "text",
            [],
        )
    )

    for i in range(n):

        word = str(
            data["text"][i]
        ).strip()

        if not word:
            continue

        try:
            confidence = float(
                data["conf"][i]
            )

        except (
            TypeError,
            ValueError,
        ):
            confidence = -1.0

        if confidence >= 0:
            confidences.append(
                confidence
            )

        key = (
            data["block_num"][i],
            data["par_num"][i],
            data["line_num"][i],
        )

        item = lines.setdefault(
            key,
            {
                "words": [],
                "boxes": [],
            },
        )

        item["words"].append(
            word
        )

        item["boxes"].append(
            (
                int(
                    data["left"][i]
                ),
                int(
                    data["top"][i]
                ),
                int(
                    data["width"][i]
                ),
                int(
                    data["height"][i]
                ),
            )
        )

    pieces = []
    boxes = []

    for item in lines.values():

        pieces.append(
            " ".join(
                item["words"]
            )
        )

        x1 = min(
            box[0]
            for box in item["boxes"]
        )

        y1 = min(
            box[1]
            for box in item["boxes"]
        )

        x2 = max(
            box[0] + box[2]
            for box in item["boxes"]
        )

        y2 = max(
            box[1] + box[3]
            for box in item["boxes"]
        )

        boxes.append(
            (
                x1,
                y1,
                x2,
                y2,
            )
        )

    average = (
        round(
            sum(confidences)
            / len(confidences),
            1,
        )
        if confidences
        else None
    )

    return (
        "\n".join(pieces),
        average,
        boxes[:MAX_LINES_PER_PAGE],
    )


# ==========================================
# HANDWRITING LINE SEGMENTATION
# ==========================================

def _projection_lines(image):
    """
    Detect approximate handwriting lines
    when Tesseract does not supply boxes.

    Requires OpenCV and NumPy.
    """

    import numpy as np
    import cv2

    gray = np.asarray(
        image.convert("L")
    )

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )

    counts = (
        binary > 0
    ).sum(axis=1)

    active = (
        counts
        > max(
            8,
            int(image.width * 0.009),
        )
    )

    intervals = []
    start = None

    for i, used in enumerate(active):

        if used and start is None:
            start = i

        if (
            start is not None
            and (
                not used
                or i == len(active) - 1
            )
        ):

            end = (
                i
                if not used
                else i + 1
            )

            if (
                9 <= end - start <= 180
            ):
                intervals.append(
                    (
                        max(
                            0,
                            start - 5,
                        ),
                        min(
                            image.height,
                            end + 5,
                        ),
                    )
                )

            start = None

    merged = []

    for top, bottom in intervals:

        if (
            merged
            and top <= merged[-1][1] + 4
        ):
            merged[-1] = (
                merged[-1][0],
                max(
                    bottom,
                    merged[-1][1],
                ),
            )

        else:
            merged.append(
                (
                    top,
                    bottom,
                )
            )

    return [
        (
            0,
            a,
            image.width,
            b,
        )
        for a, b in merged[
            :MAX_LINES_PER_PAGE
        ]
    ]


# ==========================================
# LOCAL HANDWRITING MODEL
# ==========================================

@lru_cache(maxsize=1)
def _trocr():
    """
    Load locally cached TrOCR.

    Model downloads are NOT performed
    automatically during an analysis request.
    """

    from transformers import (
        TrOCRProcessor,
        VisionEncoderDecoderModel,
    )

    processor = (
        TrOCRProcessor.from_pretrained(
            TROCR_MODEL,
            local_files_only=True,
        )
    )

    model = (
        VisionEncoderDecoderModel.from_pretrained(
            TROCR_MODEL,
            local_files_only=True,
        )
    )

    model.eval()

    return processor, model


def _handwriting(image, boxes):
    import torch

    processor, model = _trocr()

    result = []

    line_boxes = (
        boxes
        or _projection_lines(image)
    )

    for x1, y1, x2, y2 in line_boxes[
        :MAX_LINES_PER_PAGE
    ]:

        x1 = max(
            0,
            x1 - 7,
        )

        y1 = max(
            0,
            y1 - 6,
        )

        x2 = min(
            image.width,
            x2 + 7,
        )

        y2 = min(
            image.height,
            y2 + 6,
        )

        if (
            x2 - x1 < 15
            or y2 - y1 < 10
        ):
            continue

        crop = image.crop(
            (
                x1,
                y1,
                x2,
                y2,
            )
        ).convert("RGB")

        with torch.inference_mode():

            pixels = processor(
                images=crop,
                return_tensors="pt",
            ).pixel_values

            ids = model.generate(
                pixels,
                max_new_tokens=96,
            )

        text = processor.batch_decode(
            ids,
            skip_special_tokens=True,
        )[0].strip()

        if text:
            result.append(
                text
            )

    return "\n".join(result)


# ==========================================
# HYBRID OCR SELECTION
# ==========================================

def _ocr_image(image, mode):
    processed = _prepare_image(
        image
    )

    printed = ""
    confidence = None
    boxes = []

    methods = []
    warnings = []

    try:

        (
            printed,
            confidence,
            boxes,
        ) = _tesseract(
            processed
        )

        methods.append(
            "tesseract"
        )

    except (
        ImportError,
        RuntimeError,
        OSError,
    ) as exc:

        warnings.append(
            str(exc)
        )

    handwritten = ""

    handwriting_needed = (
        mode == "handwritten"
        or (
            mode == "auto"
            and (
                len(tokens(printed)) < MIN_WORDS
                or (
                    confidence is not None
                    and confidence < 50
                )
            )
        )
    )

    if handwriting_needed:

        try:

            handwritten = _handwriting(
                processed,
                boxes,
            )

            methods.append(
                "trocr"
            )

        except (
            ImportError,
            OSError,
            RuntimeError,
            ValueError,
        ):

            warnings.append(
                "TrOCR model unavailable. "
                "Install and cache the "
                "handwriting model locally."
            )

    # TrOCR does not provide Tesseract's
    # confidence metric.

    if (
        mode == "handwritten"
        and handwritten.strip()
    ):
        return (
            handwritten,
            None,
            methods,
            warnings,
        )

    if (
        handwritten
        and (
            len(tokens(handwritten))
            > len(tokens(printed))
        )
    ):
        return (
            handwritten,
            None,
            methods,
            warnings,
        )

    return (
        printed,
        confidence,
        methods,
        warnings,
    )


# ==========================================
# PDF + IMAGE PAGE EXTRACTION
# ==========================================

def _document_pages(
    contents,
    ext,
    mode,
):
    """
    Extract text from a PDF or image.

    Mixed PDFs are processed page-by-page:
    embedded text first, OCR when necessary.
    """

    if ext != ".pdf":

        image = _image_from_bytes(
            contents
        )

        (
            text,
            confidence,
            methods,
            warnings,
        ) = _ocr_image(
            image,
            mode,
        )

        return (
            [
                (
                    1,
                    text,
                    confidence,
                    methods,
                    warnings,
                )
            ],
            1,
        )

    import pymupdf
    from PIL import Image

    try:
        document = pymupdf.open(
            stream=contents,
            filetype="pdf",
        )

    except (
        RuntimeError,
        ValueError,
    ) as exc:

        raise ValueError(
            "Invalid or damaged PDF."
        ) from exc

    with document:

        if document.needs_pass:
            raise ValueError(
                "Encrypted PDF cannot be analyzed."
            )

        if len(document) > MAX_PAGES:
            raise ValueError(
                "PDF exceeds the 12-page "
                "analysis limit."
            )

        if len(document) == 0:
            raise ValueError(
                "PDF has no pages."
            )

        results = []

        for idx, page in enumerate(
            document
        ):

            embedded = page.get_text(
                "text"
            )[:MAX_TEXT_CHARS]

            # A page with enough selectable
            # text does not need OCR.
            if (
                len(tokens(embedded))
                >= MIN_WORDS
            ):

                results.append(
                    (
                        idx + 1,
                        embedded,
                        None,
                        ["pdf-text"],
                        [],
                    )
                )

                continue

            area = (
                page.rect.width
                * 180 / 72
            ) * (
                page.rect.height
                * 180 / 72
            )

            if area > MAX_PIXELS:

                results.append(
                    (
                        idx + 1,
                        embedded,
                        None,
                        [],
                        [
                            "Page resolution "
                            "exceeds OCR limit."
                        ],
                    )
                )

                continue

            try:

                pix = page.get_pixmap(
                    dpi=180,
                    alpha=False,
                    colorspace=pymupdf.csRGB,
                )

                image = Image.frombytes(
                    "RGB",
                    (
                        pix.width,
                        pix.height,
                    ),
                    pix.samples,
                )

                (
                    text,
                    confidence,
                    methods,
                    warnings,
                ) = _ocr_image(
                    image,
                    mode,
                )

                combined = "\n".join(
                    [
                        embedded,
                        text,
                    ]
                ).strip()

                results.append(
                    (
                        idx + 1,
                        combined,
                        confidence,
                        methods,
                        warnings,
                    )
                )

            except (
                RuntimeError,
                ValueError,
                OSError,
            ):

                results.append(
                    (
                        idx + 1,
                        embedded,
                        None,
                        [],
                        [
                            "Could not OCR page."
                        ],
                    )
                )

        return results, len(document)


# ==========================================
# CACHED FILE EXTRACTION
# ==========================================

def extract_file(
    file_field,
    mode="auto",
):
    if mode not in {
        "auto",
        "printed",
        "handwritten",
    }:
        raise ValidationError(
            "Invalid OCR mode."
        )

    ext = (
        "."
        + file_field.name.rsplit(
            ".",
            1,
        )[-1].lower()
        if "." in file_field.name
        else ""
    )

    if ext not in FILE_EXTENSIONS:

        return Extracted(
            status="unsupported",
            warnings=[
                "Unsupported file format."
            ],
        )

    if (
        not file_field.size
        or file_field.size > MAX_FILE_BYTES
    ):

        return Extracted(
            status="unsupported",
            warnings=[
                "File is empty or "
                "larger than 10 MB."
            ],
        )

    try:

        file_field.open("rb")

        try:

            contents = file_field.read(
                MAX_FILE_BYTES + 1
            )

        finally:
            file_field.close()

        if len(contents) > MAX_FILE_BYTES:

            raise ValueError(
                "File exceeds 10 MB."
            )

        fingerprint = hashlib.sha256(
            contents
        ).hexdigest()

        cache_key = (
            "ah-ocr:"
            + hashlib.sha256(
                (
                    f"ocr-v4|{fingerprint}|{mode}"
                ).encode()
            ).hexdigest()
        )

        cached = cache.get(
            cache_key
        )

        if cached is not None:
            return cached

        pages, total = _document_pages(
            contents,
            ext,
            mode,
        )

    except (
        ImportError,
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:

        return Extracted(
            status="unsupported",
            warnings=[
                str(exc)
            ],
        )

    text_parts = []
    confidences = []
    methods = set()
    warnings = []
    details = []

    unreadable_pages = 0
    low_confidence_pages = 0

    for (
        number,
        page_text,
        confidence,
        page_methods,
        page_warnings,
    ) in pages:

        readable = (
            len(tokens(page_text))
            >= MIN_WORDS
        )

        if not readable:
            unreadable_pages += 1

        text_parts.append(
            page_text
        )

        if confidence is not None:

            confidences.append(
                confidence
            )

            if confidence < 55:
                low_confidence_pages += 1

        methods.update(
            page_methods
        )

        warnings.extend(
            f"Page {number}: {warning}"
            for warning in page_warnings
        )

        details.append({
            "page": number,
            "words": len(tokens(page_text)),
            "method": (
                ", ".join(page_methods)
                or "none"
            ),
            "confidence": confidence,
            "readable": readable,
        })

    combined = "\n".join(
        text_parts
    )[:MAX_TEXT_CHARS]

    if (
        len(tokens(combined))
        < MIN_WORDS
    ):

        status = "unreadable"

        warnings.append(
            "Insufficient recognized text. "
            "Do not interpret as 0% plagiarism."
        )

    elif (
        unreadable_pages
        or low_confidence_pages
    ):

        status = "partial"

        if unreadable_pages:

            warnings.append(
                f"{unreadable_pages} page(s) "
                "lack sufficient OCR text; "
                "result is partial."
            )

        if low_confidence_pages:

            warnings.append(
                f"{low_confidence_pages} page(s) "
                "have low OCR confidence; "
                "manual review required."
            )

    else:
        status = "ready"

    average = (
        round(
            sum(confidences)
            / len(confidences),
            1,
        )
        if confidences
        else None
    )

    result = Extracted(
        text=combined,
        status=status,
        pages=(
            total - unreadable_pages
        ),
        total_pages=total,
        confidence=average,
        methods=sorted(
            methods
        ),
        warnings=warnings[:15],
        page_details=details,
    )

    if status in {
        "ready",
        "partial",
    }:

        cache.set(
            cache_key,
            result,
            OCR_CACHE_SECONDS,
        )

    return result


# ==========================================
# SUBMISSION TEXT SOURCE
# ==========================================

def submission_text(
    submission,
    mode="auto",
):
    """
    Supports:
    - Timed Writing
    - Regular typed answers
    - PDF submissions
    - Scanned image submissions
    """

    plain = (
        submission.text_content or ""
    ).strip()[:MAX_TEXT_CHARS]

    if not submission.submission_file:

        if len(tokens(plain)) < MIN_WORDS:

            return Extracted(
                text=plain,
                status="unreadable",
                warnings=[
                    "At least 8 words needed."
                ],
            )

        return Extracted(
            text=plain,
            status="ready",
            methods=[
                "typed-text"
            ],
        )

    result = extract_file(
        submission.submission_file,
        mode,
    )

    combined = "\n".join(
        filter(
            None,
            [
                plain,
                result.text,
            ],
        )
    )[:MAX_TEXT_CHARS]

    if (
        result.status in {
            "unreadable",
            "unsupported",
        }
        and len(tokens(plain)) >= MIN_WORDS
    ):

        status = "partial"

        warnings = (
            result.warnings
            + [
                "Attached file not analyzed; "
                "typed text only."
            ]
        )

    elif (
        result.status in {
            "ready",
            "partial",
        }
        and len(tokens(combined))
        >= MIN_WORDS
    ):

        status = result.status
        warnings = result.warnings

    else:

        status = result.status
        warnings = result.warnings

    return Extracted(
        text=combined,
        status=status,
        pages=result.pages,
        total_pages=result.total_pages,
        confidence=result.confidence,
        methods=(
            (
                ["typed-text"]
                if plain
                else []
            )
            + result.methods
        ),
        warnings=warnings,
        page_details=result.page_details,
    )


# ==========================================
# OPTIONAL SEMANTIC MODEL
# ==========================================

@lru_cache(maxsize=1)
def _semantic_model():
    from sentence_transformers import (
        SentenceTransformer,
    )

    return SentenceTransformer(
        SEMANTIC_MODEL,
        local_files_only=True,
    )


def _chunks(
    text,
    max_words=110,
    max_chunks=15,
):
    words = tokens(text)[
        :max_words * max_chunks
    ]

    return [
        " ".join(
            words[i:i + max_words]
        )
        for i in range(
            0,
            len(words),
            max_words,
        )
    ]


def semantic_score(
    source,
    candidate,
):
    """
    Returns highest local paragraph
    cosine similarity on a 0-100 scale.

    This is not plagiarism probability.
    """

    import numpy as np

    model = _semantic_model()

    left = _chunks(
        source
    )

    right = _chunks(
        candidate
    )

    if not left or not right:
        return None

    embeddings = model.encode(
        left + right,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    a = embeddings[
        :len(left)
    ]

    b = embeddings[
        len(left):
    ]

    cosine = float(
        np.max(
            a @ b.T
        )
    )

    return round(
        max(
            0.0,
            min(
                1.0,
                cosine,
            ),
        ) * 100,
        2,
    )


# ==========================================
# COMPLETE SUBMISSION ANALYSIS
# ==========================================

def analyze_submission(
    submission,
    mode="auto",
    use_semantic=False,
):
    """
    Compare only finalized submissions
    belonging to the SAME assignment.

    No database writes.
    No automatic grading.
    No academic misconduct verdict.
    """

    if submission.status not in {
        Submission.Status.SUBMITTED,
        Submission.Status.GRADED,
    }:

        raise ValidationError(
            "Only finalized submissions "
            "can be analyzed."
        )

    if mode not in {
        "auto",
        "printed",
        "handwritten",
    }:

        raise ValidationError(
            "Invalid OCR mode."
        )

    source = submission_text(
        submission,
        mode,
    )

    report = {
        "source": source,
        "matches": [],
        "checked": 0,
        "skipped": [],
        "limited": False,
        "highest_score": None,
        "semantic_enabled": False,
        "warnings": [],
        "analyzed_at": timezone.now(),
    }

    if not source.usable:

        report["warnings"].append(
            "Source has insufficient readable "
            "content: analysis unavailable."
        )

        return report

    candidates = (
        Submission.objects.filter(
            assignment_id=(
                submission.assignment_id
            ),
            status__in=[
                Submission.Status.SUBMITTED,
                Submission.Status.GRADED,
            ],
        )
        .exclude(
            pk=submission.pk
        )
        .select_related(
            "student"
        )
        .order_by(
            "pk"
        )
    )

    batch = list(
        candidates[
            :MAX_COMPARE + 1
        ]
    )

    report["limited"] = (
        len(batch) > MAX_COMPARE
    )

    semantic_available = False

    if use_semantic:

        try:

            _semantic_model()
            semantic_available = True

        except (
            ImportError,
            OSError,
            ValueError,
            TypeError,
        ):

            report["warnings"].append(
                "Semantic model not installed "
                "or cached; lexical comparison only."
            )

    report["semantic_enabled"] = (
        semantic_available
    )

    for other in batch[:MAX_COMPARE]:

        candidate = submission_text(
            other,
            mode,
        )

        if not candidate.usable:

            report["skipped"].append({
                "id": other.pk,
                "reason": (
                    "; ".join(
                        candidate.warnings
                    )
                    or "Unreadable text"
                ),
            })

            continue

        report["checked"] += 1

        lexical = lexical_score(
            source.text,
            candidate.text,
        )

        semantic = None

        if semantic_available:

            try:

                semantic = semantic_score(
                    source.text,
                    candidate.text,
                )

            except (
                RuntimeError,
                ValueError,
                OSError,
            ):

                report["warnings"].append(
                    "One semantic comparison failed."
                )

        if (
            lexical > 0
            or (
                semantic is not None
                and semantic >= 60
            )
        ):

            report["matches"].append(
                Match(
                    submission=other,
                    lexical=lexical,
                    semantic=semantic,
                    passages=matching_passages(
                        source.text,
                        candidate.text,
                    ),
                    source_status=source.status,
                    candidate_status=(
                        candidate.status
                    ),
                    candidate_confidence=(
                        candidate.confidence
                    ),
                )
            )

    report["matches"].sort(
        key=lambda match: (
            -match.lexical,
            -(match.semantic or 0),
            match.submission.pk,
        )
    )

    report["matches"] = (
        report["matches"][
            :MAX_MATCHES
        ]
    )

    if report["matches"]:

        report["highest_score"] = (
            report["matches"][0].lexical
        )

    elif (
        report["checked"] > 0
        and not report["limited"]
        and not report["skipped"]
        and source.status == "ready"
    ):

        # Zero only refers to the
        # analyzed, readable text corpus.
        report["highest_score"] = 0.0

    if report["limited"]:

        report["warnings"].append(
            "Only first 30 comparison "
            "submissions checked; "
            "report is incomplete."
        )

    return report
