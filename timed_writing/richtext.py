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
}

COLOR_RE = re.compile(
    r"^#[0-9a-fA-F]{6}$"
)


def validate_format(name, value):

    if name in BOOLEAN_FORMATS:
        if value is not True:
            raise ValidationError(
                "Invalid text formatting."
            )
        return True

    if name == "header":
        if type(value) is not int or value not in (1, 2, 3):
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
        if value not in ("sub", "super"):
            raise ValidationError(
                "Invalid script formatting."
            )

    elif name == "indent":
        if type(value) is not int or value not in range(1, 5):
            raise ValidationError(
                "Invalid indentation."
            )

    elif name in ("color", "background"):
        if (
            not isinstance(value, str)
            or not COLOR_RE.fullmatch(value)
        ):
            raise ValidationError(
                "Invalid text color."
            )

    elif name == "link":
        if not isinstance(value, str) or len(value) > 500:
            raise ValidationError(
                "Invalid hyperlink."
            )

        parsed = urlsplit(value)

        if (
            parsed.scheme not in ("https", "http")
            or not parsed.netloc
            or any(ord(c) < 33 for c in value)
        ):
            raise ValidationError(
                "Only safe HTTP/HTTPS links are allowed."
            )

    else:
        raise ValidationError(
            "Unsupported formatting."
        )

    return value


def normalize_delta(document):
    """
    Validate Quill Delta JSON.

    No raw HTML, images, video or executable
    content is accepted from the browser.

    Returns:
        (normalized_delta, plain_text)
    """

    if not isinstance(document, dict):
        raise ValidationError(
            "Invalid rich document."
        )

    if set(document.keys()) != {"ops"}:
        raise ValidationError(
            "Invalid document structure."
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
        document_bytes = len(
            json.dumps(
                document,
                ensure_ascii=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        raise ValidationError(
            "Invalid document JSON."
        )

    if document_bytes > MAX_DOCUMENT_BYTES:
        raise ValidationError(
            "Document exceeds allowed size."
        )

    cleaned_ops = []
    plain_parts = []
    plain_length = 0

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
        cleaned = {}

        if isinstance(inserted, str):
            cleaned["insert"] = inserted
            readable = inserted

        elif isinstance(inserted, dict):

            if set(inserted) == {"formula"}:

                formula = inserted["formula"]

                if (
                    not isinstance(formula, str)
                    or not formula.strip()
                    or len(formula) > 2000
                ):
                    raise ValidationError(
                        "Invalid mathematical formula."
                    )

                # Disallow HTML-capable LaTeX commands.
                if re.search(
                    r"\\(?:href|url|html\w*|includegraphics)\b",
                    formula,
                    re.IGNORECASE,
                ):
                    raise ValidationError(
                        "Unsupported formula command."
                    )

                cleaned["insert"] = {
                    "formula": formula
                }

                readable = (
                    "[Formula: " + formula + "]"
                )

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
                    kind not in ALLOWED_SHAPES
                    or not isinstance(label, str)
                    or len(label) > 80
                ):
                    raise ValidationError(
                        "Invalid shape properties."
                    )

                cleaned["insert"] = {
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

            else:
                raise ValidationError(
                    "Unsupported embedded content."
                )

        else:
            raise ValidationError(
                "Invalid document content."
            )

        attributes = operation.get(
            "attributes",
            {},
        )

        if not isinstance(attributes, dict):
            raise ValidationError(
                "Invalid formatting attributes."
            )

        validated_attributes = {}

        for name, value in attributes.items():

            if name not in ALLOWED_FORMATS:
                raise ValidationError(
                    "Unsupported formatting attribute."
                )

            validated_attributes[name] = (
                validate_format(name, value)
            )

        if validated_attributes:
            cleaned["attributes"] = (
                validated_attributes
            )

        cleaned_ops.append(cleaned)

        plain_length += len(readable)

        if plain_length > MAX_TEXT_LENGTH:
            raise ValidationError(
                "Answer exceeds 100,000 characters."
            )

        plain_parts.append(readable)

    plain_text = "".join(plain_parts)

    return {
        "ops": cleaned_ops
    }, plain_text