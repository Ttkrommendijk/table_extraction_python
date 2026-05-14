def _is_year_cell(content):
    value = (content or "").strip()
    return value.isdigit() and len(value) == 4


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
