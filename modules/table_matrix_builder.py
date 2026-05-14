from collections import defaultdict

from modules.column_detector import (
    detect_numeric_columns,
    is_numeric,
    is_small_note_reference,
)
from modules.table_region_detector import split_side_by_side_regions, detect_table_regions


NOISE_WORDS = {
    "ff",
}

# Klippa compatibility principle:
# Preserve the visual grid first. Do not remove rows just because they look
# semantically redundant. Only remove obvious material outside tables, such as
# signatures and footer narratives, because Klippa usually does not include
# those in the table component.
FOOTER_KEYWORDS = {
    "reconhecemos",
    "assinado",
    "assinatura",
    "cpf:",
    "cnpj/cpf",
    "crc",
    "avenida",
    "pabx",
    "www.",
    "contador",
    "contadora",
    "parte integrante",
    "demonstrações financeiras",
    "demonstracoes financeiras",
}

FINAL_TOTAL_TERMS = {
    "total ativo",
    "total do ativo",
    "total passivo",
    "total do passivo",
    "total passivo e patrimonio",
    "total passivo e patrimônio",
    "total do passivo e patrimonio",
    "total do passivo e patrimônio",
}

HEADER_TERMS = {
    "nota",
    "notas",
    "explicativa",
    "explicativas",
    "controladora",
    "consolidado",
    "individual",
    "r$",
    "$",
}

TABLE_START_TERMS = {
    "ativo",
    "passivo",
    "patrimônio",
    "patrimonio",
    "resultado",
    "receita",
    "contas",
    "nota",
    "notas",
}

METADATA_TITLE_TERMS = {
    "demonstração do resultado",
    "demonstracao do resultado",
    "demonstração de resultado",
    "demonstracao de resultado",
    "demonstração dos resultados",
    "demonstracao dos resultados",
    "balanço patrimonial",
    "balanco patrimonial",
    "unidades de reais",
    "em unidades de reais",
    "em milhares",
    "milhares de reais",
}


# =========================================================
# column helpers
# =========================================================

def _column_x(column):
    if isinstance(column, dict):
        return column["x"]
    return column


def _normalize_columns(columns):
    return sorted([_column_x(c) for c in columns])


def _nearest_index(value, positions):
    distances = [abs(value - pos) for pos in positions]
    return distances.index(min(distances))


def _row_text(row):
    return " ".join(w.get("text", "") for w in row.get("words", [])).strip()


def _row_text_lower(row):
    return _row_text(row).lower()


def _has_header_term(text):
    normalized = text.strip().lower()

    if normalized in HEADER_TERMS:
        return True

    if normalized.isdigit() and len(normalized) == 4:
        return True

    if "/" in normalized and any(ch.isdigit() for ch in normalized):
        return True

    return False


def _row_is_header_like(row):
    words = row.get("words", [])

    if not words:
        return False

    text = _row_text_lower(row)
    header_hits = sum(
        1
        for word in words
        if _has_header_term(word.get("text", ""))
    )

    return (
        header_hits >= 1
        or "controladora" in text
        or "consolidado" in text
        or "individual" in text
        or "31/" in text
    )


def _has_note_column(rows, value_columns):
    if not value_columns:
        return False

    first_value_x = value_columns[0]
    note_like_count = 0

    for row in rows:
        for word in row.get("words", []):
            text = word["text"].strip().lower()
            x = word["center_x"]

            if x < first_value_x and (
                is_small_note_reference(text)
                or text in {"nota", "notas", "explicativa", "explicativas"}
            ):
                note_like_count += 1

    return note_like_count >= 1


def _note_column_x(rows, first_value_x):
    candidates = []

    for row in rows:
        for word in row.get("words", []):
            text = word["text"].strip().lower()
            x = word["center_x"]

            if x < first_value_x and (
                is_small_note_reference(text)
                or text in {"nota", "notas", "explicativa", "explicativas"}
            ):
                candidates.append(x)

    if not candidates:
        return None

    return sum(candidates) / len(candidates)


def _build_column_anchors(rows, numeric_columns):
    """
    Create Klippa-style visual column anchors.

    The first column is always label. If a note column is visually present,
    it becomes column 1. Numeric/value columns follow. This is deliberately
    geometry-first and does not flatten multi-row headers into semantic names.
    """

    value_columns = _normalize_columns(numeric_columns)
    anchors = [{"index": 0, "x": None, "type": "label"}]

    has_note_column = _has_note_column(rows, value_columns)

    if has_note_column:
        first_value_x = value_columns[0] if value_columns else float("inf")
        note_x = _note_column_x(rows, first_value_x)
        anchors.append({"index": 1, "x": note_x, "type": "note"})

    start_index = len(anchors)

    for offset, x in enumerate(value_columns):
        anchors.append(
            {
                "index": start_index + offset,
                "x": x,
                "type": "value",
            }
        )

    return anchors


def _value_anchor_positions(anchors):
    return [a["x"] for a in anchors if a["type"] == "value" and a["x"] is not None]


def _note_anchor(anchors):
    for anchor in anchors:
        if anchor["type"] == "note":
            return anchor
    return None


def _nearest_anchor_index(x, anchors, allowed_types=None):
    candidates = []

    for anchor in anchors:
        if anchor["x"] is None:
            continue

        if allowed_types and anchor["type"] not in allowed_types:
            continue

        candidates.append(anchor)

    if not candidates:
        return 0

    best = min(candidates, key=lambda a: abs(x - a["x"]))
    return best["index"]


def _assign_word_to_column(word, anchors, row_is_header_like):
    text = word["text"].strip()
    lower = text.lower()
    center_x = word["center_x"]

    note_anchor = _note_anchor(anchors)
    value_positions = _value_anchor_positions(anchors)

    if note_anchor and note_anchor["x"] is not None:
        if (
            abs(center_x - note_anchor["x"]) <= 120
            and (
                is_small_note_reference(text)
                or lower in {"nota", "notas", "explicativa", "explicativas"}
            )
        ):
            return note_anchor["index"]

    if is_numeric(text) or text.upper() in {"R$", "$"}:
        if value_positions:
            return _nearest_anchor_index(center_x, anchors, allowed_types={"value"})
        return 1 if len(anchors) > 1 else 0

    # Klippa preserves multi-row headers as a visual grid. Header terms such as
    # Controladora, Consolidado, Individual and year/date labels should stay in
    # the columns where they visually appear instead of being collapsed into the
    # left label column.
    if row_is_header_like and _has_header_term(text):
        if note_anchor and lower in {"nota", "notas", "explicativa", "explicativas"}:
            return note_anchor["index"]

        if value_positions:
            return _nearest_anchor_index(center_x, anchors, allowed_types={"value"})

    # For all ordinary alphabetic content, keep Klippa-like row labels intact in
    # column 0. Do not split normal labels into several text columns.
    return 0


# =========================================================
# matrix creation
# =========================================================

def rows_to_matrix(rows, numeric_columns=None):
    if numeric_columns is None:
        numeric_columns = detect_numeric_columns(rows)

    anchors = _build_column_anchors(rows, numeric_columns)
    column_count = max((a["index"] for a in anchors), default=0) + 1

    matrix = []

    for row in rows:
        row_cells = defaultdict(list)
        row_is_header_like = _row_is_header_like(row)

        for word in row.get("words", []):
            text = word["text"].strip()

            if not text:
                continue

            if text.lower() in NOISE_WORDS:
                continue

            col = _assign_word_to_column(
                word,
                anchors,
                row_is_header_like,
            )

            row_cells[col].append(text)

        matrix_row = []

        for col in range(column_count):
            content = " ".join(row_cells.get(col, [])).strip()
            matrix_row.append(content)

        # Preserve visual rows that contain any text/value. Do not remove sparse
        # rows, because Klippa keeps many sparse subtotal/header rows.
        if any(cell.strip() for cell in matrix_row):
            matrix.append(matrix_row)

    return matrix


def normalize_matrix(matrix):
    if not matrix:
        return []

    max_columns = max(len(row) for row in matrix)
    normalized = []

    for row in matrix:
        row = row[:]

        while len(row) < max_columns:
            row.append("")

        normalized.append(row)

    return normalized


# =========================================================
# Klippa-compatible row preservation and light cropping
# =========================================================

def _row_has_values(row):
    return any(cell.strip() for cell in row[1:])


def _is_footer_row(row):
    text = " ".join(row).lower()
    return any(keyword in text for keyword in FOOTER_KEYWORDS)


def _looks_like_table_start(row):
    text = " ".join(row).lower().strip()

    if not text:
        return False

    # Do not let page titles or unit lines start a table. Klippa usually starts
    # DRE tables at the real grid header, for example "Notas | 31/12/...",
    # not at the narrative title above it.
    if _is_metadata_title_text(text):
        return False

    # A title-only line such as "resultados" is page metadata, not the table.
    title_only_terms = {"resultado", "resultados"}
    if text in title_only_terms:
        return False

    if any(term in text for term in {"nota", "notas", "controladora", "consolidado"}):
        return True

    if any(cell.strip().isdigit() and len(cell.strip()) == 4 for cell in row):
        return True

    if any(term in text for term in TABLE_START_TERMS):
        return _row_has_values(row) or text in {"ativo", "passivo", "patrimônio", "patrimonio"}

    return False


def _normalize_text_for_matching(text):
    replacements = {
        "á": "a",
        "à": "a",
        "â": "a",
        "ã": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }

    normalized = text.lower()

    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    return " ".join(normalized.split())



def _is_metadata_title_text(text):
    normalized = _normalize_text_for_matching(text)

    return any(term in normalized for term in METADATA_TITLE_TERMS)

def _is_final_total_row(row):
    """
    Detect strong balance-sheet final total rows.

    These rows normally mark the end of a side-by-side financial table. Text
    after them is often signature, certification or footer material, and should
    not be attached to the table component.
    """

    text = _normalize_text_for_matching(" ".join(row))

    return any(term in text for term in FINAL_TOTAL_TERMS)


def filter_non_table_rows(matrix):
    """
    Klippa compatibility filter.

    This intentionally does NOT clean or semantically improve table rows. It
    only removes obvious pre-table metadata and obvious post-table footer or
    signature rows. Once a table starts, sparse rows, section rows, subtotal rows
    and multi-level headers are preserved.
    """

    if not matrix:
        return []

    filtered = []
    started = False
    seen_numeric_table_row = False
    seen_total = False

    for row in matrix:
        row_text = " ".join(row).lower().strip()

        if _is_footer_row(row):
            break

        if "notas explicativas" in row_text and seen_numeric_table_row:
            break

        if not started:
            if _is_metadata_title_text(row_text):
                continue

            if _looks_like_table_start(row):
                started = True
            else:
                continue

        if _row_has_values(row):
            seen_numeric_table_row = True

        if "total" in row_text:
            seen_total = True

        if "".join(row).strip() == "":
            continue

        filtered.append(row)

        # Strong final-total rows close the current visual table. This prevents
        # trailing signatures, certification text and footer fragments from being
        # serialized as extra table rows.
        if seen_numeric_table_row and _is_final_total_row(row):
            break

    return filtered


def _is_year_cell(cell):
    value = cell.strip()
    return value.isdigit() and len(value) == 4


def _is_year_row(row):
    return sum(1 for cell in row if _is_year_cell(cell)) >= 2


def _join_nonempty(*parts):
    return " ".join(part.strip() for part in parts if part and part.strip()).strip()


def _merge_note_header(cell_a, cell_b):
    text = _join_nonempty(cell_a, cell_b)
    normalized = text.lower()

    if normalized in {"nota explicativa", "nota explicativas", "notas explicativas"}:
        return "Nota explicativa"

    return text


def merge_multiline_rows(matrix):
    """Normalize the most common Klippa-style multi-line headers.

    OCRParse often emits the first table header as three rows:
    row 0: "Nota"
    row 1: table title + "explicativa" + group labels
    row 2: years

    Klippa emits this as two header rows, with "Nota explicativa" merged and
    years on the second header row. Keep this rule deliberately narrow so body
    rows remain visual and untouched.
    """

    if len(matrix) < 2:
        return matrix

    rows = [row[:] for row in matrix]
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    if len(rows) >= 3 and _is_year_row(rows[2]):
        r0, r1, r2 = rows[0], rows[1], rows[2]
        combined = [""] * width

        combined[0] = _join_nonempty(r0[0], r1[0])

        if width > 1:
            combined[1] = _merge_note_header(r0[1], r1[1])

        for idx in range(2, width):
            combined[idx] = _join_nonempty(r0[idx], r1[idx])

        if combined[1].lower() == "nota explicativa" or any(
            cell.lower() in {"controladora", "consolidado", "individual"}
            for cell in combined
        ):
            return [combined, r2] + rows[3:]

    if len(rows) >= 2 and _is_year_row(rows[1]):
        return rows

    return rows


def reconstruct_matrices_from_rows(rows):
    """
    One OCR page can contain one or more table regions. This function detects
    side-by-side regions first, then reconstructs each region as a Klippa-like
    visual grid. No semantic cleanup is performed here.
    """

    regions = split_side_by_side_regions(rows)
    matrices = []

    for region_rows in regions:
        if not region_rows:
            continue

        numeric_columns = detect_numeric_columns(region_rows)
        matrix = rows_to_matrix(region_rows, numeric_columns)
        matrix = normalize_matrix(matrix)
        matrix = filter_non_table_rows(matrix)
        matrix = merge_multiline_rows(matrix)
        matrix = normalize_matrix(matrix)

        if matrix:
            matrices.append(matrix)

    return matrices


# klippa compatibility helper
def build_table_regions(rows):
    return detect_table_regions(rows)
