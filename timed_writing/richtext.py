
import json
import re

from urllib.parse import urlsplit

from django.core.exceptions import ValidationError


MAX_DOCUMENT_BYTES = 400_000
MAX_TEXT_LENGTH = 100_000
MAX_OPERATIONS = 3000


ALLOWED_SHAPES = {
    "rectangle",
    "circle",
    "diamond",
    "arrow",
    "line",
}


BOOLEAN_FORMATS = {
    "bold",
    "italic",
    "underline",
    "strike",
    "blockquote",
}


ALLOWED_FORMATS = BOOLEAN_FORMATS | {
    "header",
    "align",
    "list",
    "script",
    "color",
    "background",
    "link",
    "indent",
    "font",
    "size",
    "lineheight",
}


COLOR_RE = re.compile(
    r"^#[0-9a-fA-F]{6}$"
)


ALLOWED_FONTS = {
    "arial",
    "serif",
    "monospace",
}


ALLOWED_SIZES = {
    "12px",
    "14px",
    "16px",
    "18px",
    "24px",
    "32px",
}


ALLOWED_LINE_HEIGHTS = {
    "single",
    "normal",
    "relaxed",
    "double",
}


BAD_TEX = re.compile(
    r"\\(?:href|url|html\w*|includegraphics)\b",
    re.I,
)


# ==========================================
# FORMAT ATTRIBUTE VALIDATION
# ==========================================

def validate_format(name, value):

    if name in BOOLEAN_FORMATS:

        if value is not True:
            raise ValidationError(
                "Invalid text formatting."
            )

        return True

    if name == "header":

        if (
            type(value) is not int
            or value not in (1, 2, 3)
        ):
            raise ValidationError(
                "Invalid heading level."
            )

    elif name == "align":

        if value not in (
            "center",
            "right",
            "justify",
        ):
            raise ValidationError(
                "Invalid alignment."
            )

    elif name == "list":

        if value not in (
            "ordered",
            "bullet",
        ):
            raise ValidationError(
                "Invalid list type."
            )

    elif name == "script":

        if value not in (
            "sub",
            "super",
        ):
            raise ValidationError(
                "Invalid script formatting."
            )

    elif name == "indent":

        if (
            type(value) is not int
            or value not in range(1, 5)
        ):
            raise ValidationError(
                "Invalid indentation."
            )

    elif name in (
        "color",
        "background",
    ):

        if (
            not isinstance(value, str)
            or not COLOR_RE.fullmatch(value)
        ):
            raise ValidationError(
                "Invalid text color."
            )

    elif name == "font":

        if (
            not isinstance(value, str)
            or value not in ALLOWED_FONTS
        ):
            raise ValidationError(
                "Invalid font."
            )

    elif name == "size":

        if (
            not isinstance(value, str)
            or value not in ALLOWED_SIZES
        ):
            raise ValidationError(
                "Invalid font size."
            )

    elif name == "lineheight":

        if (
            not isinstance(value, str)
            or value not in ALLOWED_LINE_HEIGHTS
        ):
            raise ValidationError(
                "Invalid line spacing."
            )

    elif name == "link":

        if (
            not isinstance(value, str)
            or len(value) > 500
        ):
            raise ValidationError(
                "Invalid hyperlink."
            )

        try:
            parsed = urlsplit(value)

        except ValueError as exc:
            raise ValidationError(
                "Invalid hyperlink."
            ) from exc

        if (
            parsed.scheme not in (
                "https",
                "http",
            )
            or not parsed.netloc
            or any(
                ord(c) < 33
                for c in value
            )
        ):
            raise ValidationError(
                "Only safe HTTP/HTTPS links are allowed."
            )

    else:
        raise ValidationError(
            "Unsupported formatting."
        )

    return value


# ==========================================
# QUILL DOCUMENT NORMALIZATION
# ==========================================

def normalize_delta(document):
    """
    Validate a Quill 2 document without
    accepting untrusted raw HTML.

    Returns:

        (
            cleaned_delta,
            readable_plain_text,
        )

    Plain text remains in Submission.text_content
    for the existing grading, search and
    timed-writing service logic.
    """

    if (
        not isinstance(document, dict)
        or set(document) != {"ops"}
    ):
        raise ValidationError(
            "Invalid rich document."
        )

    ops = document["ops"]

    if (
        not isinstance(ops, list)
        or not ops
        or len(ops) > MAX_OPERATIONS
    ):
        raise ValidationError(
            "Invalid document operations."
        )

    try:

        size = len(
            json.dumps(
                document,
                ensure_ascii=False,
            ).encode("utf-8")
        )

    except (
        ValueError,
        TypeError,
        UnicodeError,
    ) as exc:

        raise ValidationError(
            "Invalid document JSON."
        ) from exc

    if size > MAX_DOCUMENT_BYTES:
        raise ValidationError(
            "Document exceeds allowed size."
        )

    cleaned_ops = []
    plain_parts = []
    plain_length = 0

    # --------------------------------------
    # VALIDATE EACH DELTA OPERATION
    # --------------------------------------

    for operation in ops:

        if (
            not isinstance(operation, dict)
            or "insert" not in operation
            or set(operation) - {
                "insert",
                "attributes",
            }
        ):
            raise ValidationError(
                "Unsupported document operation."
            )

        inserted = operation["insert"]

        # ----------------------------------
        # NORMAL TEXT
        # ----------------------------------

        if isinstance(inserted, str):

            cleaned_insert = inserted
            readable = inserted

        # ----------------------------------
        # CUSTOM EMBEDS
        # ----------------------------------

        elif isinstance(inserted, dict):

            # MATHEMATICAL FORMULA

            if set(inserted) == {"formula"}:

                formula = inserted["formula"]

                if (
                    not isinstance(formula, str)
                    or not formula.strip()
                    or len(formula) > 2000
                    or BAD_TEX.search(formula)
                ):
                    raise ValidationError(
                        "Invalid mathematical formula."
                    )

                cleaned_insert = {
                    "formula": formula
                }

                readable = (
                    "[Formula: "
                    + formula
                    + "]"
                )

            # SHAPE EMBED

            elif set(inserted) == {"shape"}:

                shape = inserted["shape"]

                if (
                    not isinstance(shape, dict)
                    or set(shape) != {
                        "kind",
                        "label",
                    }
                ):
                    raise ValidationError(
                        "Invalid shape."
                    )

                kind = shape["kind"]
                label = shape["label"]

                if (
                    not isinstance(kind, str)
                    or kind not in ALLOWED_SHAPES
                    or not isinstance(label, str)
                    or len(label) > 80
                ):
                    raise ValidationError(
                        "Invalid shape properties."
                    )

                cleaned_insert = {
                    "shape": {
                        "kind": kind,
                        "label": label,
                    }
                }

                readable = (
                    "[Shape: "
                    + kind
                    + " "
                    + label
                    + "]"
                )

            # TABLE EMBED

           
           

            elif set(inserted) in (
                {"ahTable"},
                {"table"},
            ):

                table = inserted.get(
                    "ahTable",
                    inserted.get("table"),
                )

                if (
                    not isinstance(table, dict)
                    or set(table) != {"rows"}
                ):
                    raise ValidationError(
                        "Invalid table structure."
                    )

                rows = table["rows"]

                if (
                    not isinstance(rows, list)
                    or not 1 <= len(rows) <= 10
                ):
                    raise ValidationError(
                        "Table must contain 1–10 rows."
                    )

                if not isinstance(rows[0], list):
                    raise ValidationError(
                        "Invalid table row."
                    )

                width = len(rows[0])

                if not 1 <= width <= 8:
                    raise ValidationError(
                        "Table must contain 1–8 columns."
                    )

                clean_rows = []

                for row in rows:

                    if (
                        not isinstance(row, list)
                        or len(row) != width
                    ):
                        raise ValidationError(
                            "Table must be rectangular."
                        )

                    clean_row = []

                    for cell in row:

                        if (
                            not isinstance(cell, str)
                            or len(cell) > 400
                            or "\x00" in cell
                        ):
                            raise ValidationError(
                                "Invalid table cell."
                            )

                        clean_row.append(cell)

                    clean_rows.append(clean_row)

                cleaned_insert = {
                    "ahTable": {
                        "rows": clean_rows
                    }
                }

                readable = (
                    "[Table: "
                    + "; ".join(
                        " | ".join(row)
                        for row in clean_rows
                    )
                    + "]"
                )

            # ==================================
            # ASSIGNHUB HORIZONTAL RULE
            # New: ahRule
            # Legacy: rule
            # ==================================

            elif (
                set(inserted) in (
                    {"ahRule"},
                    {"rule"},
                )
                and (
                    inserted.get(
                        "ahRule",
                        inserted.get("rule"),
                    )
                    is True
                )
            ):

                cleaned_insert = {
                    "ahRule": True
                }

                readable = "\n"

        # ----------------------------------
        # VALIDATE FORMATTING ATTRIBUTES
        # ----------------------------------

        attributes = operation.get(
            "attributes",
            {},
        )

        if not isinstance(
            attributes,
            dict,
        ):
            raise ValidationError(
                "Invalid formatting attributes."
            )

        validated = {}

        for name, value in attributes.items():

            if name not in ALLOWED_FORMATS:
                raise ValidationError(
                    "Unsupported formatting attribute."
                )

            validated[name] = validate_format(
                name,
                value,
            )

        # ----------------------------------
        # BUILD CLEAN DELTA
        # ----------------------------------

        cleaned = {
            "insert": cleaned_insert
        }

        if validated:
            cleaned["attributes"] = validated

        cleaned_ops.append(cleaned)

        # ----------------------------------
        # PLAIN TEXT SIZE CHECK
        # ----------------------------------

        plain_length += len(readable)

        if plain_length > MAX_TEXT_LENGTH:
            raise ValidationError(
                "Answer exceeds 100,000 characters."
            )

        plain_parts.append(readable)

    return (
        {"ops": cleaned_ops},
        "".join(plain_parts),
    )
