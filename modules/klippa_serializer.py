import re

try:
    from .ocrparse_loader import extract_text_content, get_last_ocrparse_json
except ImportError:  # pragma: no cover - supports direct script execution
    from ocrparse_loader import extract_text_content, get_last_ocrparse_json


def _is_period_cell(content):
    value = (content or "").strip().lower()

    if not value:
        return False

    # Accept period headers with a qualifier suffix, e.g.
    # "2022 (Reapresentado)". The period remains the structural anchor.
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()

    if re.fullmatch(r"(?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"\d{1,2}\s*/\s*\d{1,2}(?:\s*/\s*\d{2,4})?", value):
        return True

    if re.fullmatch(r"\d{1,2}[/-](?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"[a-zçãáàâéêíóôõú]{3,12}[/-](?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"[a-zçãáàâéêíóôõú]{3,12}\s+(?:19|20)\d{2}", value):
        return True

    return False


def _is_year_cell(content):
    return _is_period_cell(content)


def _row_contains_header_terms(row):
    text = " ".join(row).lower()
    return any(
        term in text
        for term in [
            "nota explicativa",
            "nota",
            "controladora",
            "consolidado",
            "individual",
        ]
    )


def _is_header_row(matrix, row_index):
    if row_index >= 2:
        return False

    row = matrix[row_index]

    if row_index == 0:
        return _row_contains_header_terms(row) or any(cell.strip() for cell in row)

    return sum(1 for cell in row if _is_year_cell(cell)) >= 2


def serialize_matrix_to_klippa_table(
    matrix,
    document_index=0,
):
    """
    Serialize a visual matrix to the Klippa table shape.

    Header rows are inferred from the normalized matrix. Klippa commonly marks
    the label/group header row and the year row as headers.
    """

    cells = []

    row_count = len(matrix)
    column_count = max((len(row) for row in matrix), default=0)

    for row_index, row in enumerate(matrix):
        is_header = _is_header_row(matrix, row_index)

        for column_index in range(column_count):
            content = row[column_index] if column_index < len(row) else ""

            cells.append(
                {
                    "row_index": row_index,
                    "column_index": column_index,
                    "content": content,
                    "header": is_header,
                }
            )

    return {
        "document": document_index,
        "row_count": row_count,
        "column_count": column_count,
        "cells": cells,
    }



def serialize_klippa_result(tables, text_content=None, version="1"):
    """Build the full Klippa-compatible OCR result envelope.

    Shape:
    {
        "ocr_result_klippa": {
            "version": "1",
            "components": {
                "tables": {
                    "tables": [...]
                }
            },
            "text_content": [...]
        }
    }

    ``tables`` must already be serialized Klippa-style table dictionaries.
    ``text_content`` is a list of extracted page text strings. It defaults to
    an empty list to keep the key present even when text extraction was not
    supplied by the caller.
    """

    if text_content is None:
        ocr_json = get_last_ocrparse_json()
        text_content = extract_text_content(ocr_json) if ocr_json else []

    return {
        "ocr_result_klippa": {
            "version": version,
            "components": {
                "tables": {
                    "tables": tables,
                }
            },
            "text_content": text_content,
        }
    }


def attach_text_content_to_klippa_result(result, text_content):
    """Add text_content to an existing result in place.

    This helper is useful for existing pipeline code that already creates the
    result envelope manually. It preserves all current table data and adds or
    replaces text_content as a sibling of components. If an older result has
    components.tables.text_content, it is moved to the new root-level location.
    """

    root = result.setdefault("ocr_result_klippa", {})
    root.setdefault("version", "1")
    components = root.setdefault("components", {})
    tables_component = components.setdefault("tables", {})
    tables_component.setdefault("tables", [])
    tables_component.pop("text_content", None)
    root["text_content"] = text_content or []
    return result


def serialize_klippa_result_from_ocrparse(tables, ocr_json, version="1"):
    """Build the Klippa-compatible result using ParsedResults[n].ParsedText.

    This is the safest entry point for runners that have the OCRParse JSON
    available at serialization time. It guarantees that
    root-level text_content is populated from ParsedText per page.
    """

    return serialize_klippa_result(
        tables,
        text_content=extract_text_content(ocr_json),
        version=version,
    )
