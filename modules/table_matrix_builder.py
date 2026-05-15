from collections import defaultdict
import re

from modules.column_detector import (
    detect_numeric_columns,
    is_numeric,
    is_small_note_reference,
)
from modules.table_region_detector import split_side_by_side_regions, detect_table_regions
from modules.financial_token_normalizer import normalize_financial_tokens_in_rows


NOISE_WORDS = {
    "ff",
    "러러",
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

def _normalize_line_text_for_compare(text):
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _line_text_has_amount(text):
    """Return True when source LineText appears to include value columns.

    We only use OCRParse LineText to restore labels. If the line text contains
    amount-like values, it is probably a whole visual row rather than a label
    segment and should not replace the label cell.
    """

    return bool(
        re.search(r"\d{1,3}(?:[.]\d{3})+(?:,\d+)?", text)
        or re.search(r"\d+,\d{2}", text)
    )


def _visible_text_is_partial_line(full_text, visible_text):
    full = _normalize_line_text_for_compare(full_text)
    visible = _normalize_line_text_for_compare(visible_text)

    if not full or not visible:
        return False

    if full == visible:
        return False

    return visible in full


def _has_latin_alpha(text):
    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", text or ""))


def _is_hierarchical_reference(text):
    value = (text or "").strip()

    if not re.fullmatch(r"\d+(?:[.]\d+)+", value):
        return False

    parts = value.split(".")

    if not all(1 <= len(part) <= 3 for part in parts):
        return False

    # Values such as 1.183.495 are thousands-formatted amounts, not account
    # references. Account/code references usually contain at least one compact
    # subgroup such as 01, 02, 10, etc.
    if len(parts) >= 2 and all(len(part) == 3 for part in parts[1:]):
        return False

    return True


def _is_reference_token(text):
    value = (text or "").strip()
    return is_small_note_reference(value) or _is_hierarchical_reference(value)


def _word_is_part_of_period(word):
    line_text = (word.get("line_text") or "").strip()
    compact_line_text = re.sub(r"\s+", "", line_text)
    return _is_period_cell(line_text) or _is_period_cell(compact_line_text)


def _line_has_alpha(words):
    return any(_has_latin_alpha(w.get("text", "")) for w in words)


def _line_words_text(words):
    return " ".join(w.get("text", "").strip() for w in sorted(words, key=lambda w: w.get("x1", 0)) if w.get("text", "").strip())


def _source_line_text(word):
    return word.get("line_text", "").strip()


def _source_line_is_label_like(full_text):
    normalized = _normalize_line_text_for_compare(full_text)

    if not normalized:
        return False

    if _line_text_has_amount(full_text):
        return False

    # Do not move visual headers such as Nota, Controladora, Consolidado,
    # Individual or currency markers into the label column. These should keep
    # their geometric column assignment.
    if normalized in HEADER_TERMS:
        return False

    if "r$" in normalized or "$" in normalized:
        return False

    if not _has_latin_alpha(normalized):
        return False

    return True


def _should_restore_label_from_source_line(full_text, visible_words):
    """Decide whether to use OCRParse LineText for the label cell.

    OCRParse LineText is useful for preserving word order, but it must not be
    used blindly when the same source line also contains note references. In
    those cases, restoring the full line leaks notes such as "9 e 11" into the
    label cell.
    """

    if not _source_line_is_label_like(full_text):
        return False

    if not _line_has_alpha(visible_words):
        return False

    # If the OCR line contains compact note references, keep the geometric
    # label/note split instead of restoring the entire source line.
    if any(is_small_note_reference(w.get("text", "").strip()) for w in visible_words):
        return False

    if re.search(r"\b\d{1,2}\s+e\s+\d{1,2}\b", full_text, flags=re.IGNORECASE):
        return False

    return True


def _restore_label_cells_from_source_lines(row, row_cells):
    """Restore OCRParse label line order without leaking notes/values.

    Only full source lines that are independently label-like are restored. Do
    not append other row words here, because note fragments like the "e" in
    "9 e 11" can otherwise leak back into the label cell. Header-like rows are
    skipped so visual header cells in value columns are not duplicated into the
    left label cell.
    """

    if _row_is_header_like(row):
        return row_cells

    words_by_line = defaultdict(list)

    for word in row.get("words", []):
        line_id = word.get("line_id")

        if line_id is None:
            continue

        words_by_line[line_id].append(word)

    restored_lines = []

    for line_id, words in sorted(words_by_line.items()):
        full_text = _source_line_text(words[0])

        if _should_restore_label_from_source_line(full_text, words):
            restored_lines.append(full_text)

    if restored_lines:
        row_cells[0] = restored_lines

    return row_cells



def _is_period_cell(text):
    value = (text or "").strip().lower()

    if not value:
        return False

    if re.fullmatch(r"(?:19|20)\d{2}", value):
        return True

    compact_value = re.sub(r"\s+", "", value)

    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", compact_value):
        return True

    if re.fullmatch(r"\d{1,2}[/-](?:19|20)\d{2}", compact_value):
        return True

    if re.fullmatch(r"[a-zçãáàâéêíóôõú]{3,12}[/-](?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"[a-zçãáàâéêíóôõú]{3,12}\s+(?:19|20)\d{2}", value):
        return True

    return False


def _has_header_term(text):
    normalized = text.strip().lower()

    if normalized in HEADER_TERMS:
        return True

    if _is_period_cell(normalized):
        return True

    return False


def _row_is_header_like(row):
    words = row.get("words", [])

    if not words:
        return False

    if any(_is_period_cell(word.get("text", "")) for word in words):
        return True

    value_like_words = sum(1 for word in words if is_numeric(word.get("text", "").strip()))
    alpha_words = sum(1 for word in words if _has_latin_alpha(word.get("text", "")))

    return alpha_words >= 1 and value_like_words <= 1

def _reference_column_x(rows, first_value_x):
    candidates = []

    for row in rows:
        for word in row.get("words", []):
            text = word["text"].strip().lower()
            x = word["center_x"]

            if x < first_value_x and _is_reference_token(text) and not _word_is_part_of_period(word):
                candidates.append(x)

    if not candidates:
        return None

    return sum(candidates) / len(candidates)


def _median(values):
    if not values:
        return None

    values = sorted(values)
    return values[len(values) // 2]


def _has_leading_reference_column(rows, first_value_x, reference_x):
    if reference_x is None:
        return False

    alpha_xs = []

    for row in rows:
        has_reference = any(
            word["center_x"] < first_value_x
            and abs(word["center_x"] - reference_x) <= 160
            and _is_reference_token(word.get("text", ""))
            and not _word_is_part_of_period(word)
            for word in row.get("words", [])
        )

        if not has_reference:
            continue

        for word in row.get("words", []):
            if word["center_x"] < first_value_x and _has_latin_alpha(word.get("text", "")):
                alpha_xs.append(word["center_x"])

    median_alpha_x = _median(alpha_xs)

    if median_alpha_x is None:
        return False

    return reference_x + 100 < median_alpha_x


def _has_note_column(rows, value_columns):
    if not value_columns:
        return False

    first_value_x = value_columns[0]
    note_x = _reference_column_x(rows, first_value_x)

    if note_x is None:
        return False

    return not _has_leading_reference_column(rows, first_value_x, note_x)


def _note_column_x(rows, first_value_x):
    return _reference_column_x(rows, first_value_x)

def _build_column_anchors(rows, numeric_columns):
    """
    Create Klippa-style visual column anchors.

    If a repeated leading reference/code column is visually present before the
    label text, it becomes column 0 and the label becomes column 1. Otherwise,
    the first column remains the label. This is geometry-first and avoids
    relying on specific header words.
    """

    value_columns = _normalize_columns(numeric_columns)
    first_value_x = value_columns[0] if value_columns else float("inf")
    reference_x = _reference_column_x(rows, first_value_x)
    has_leading_reference = _has_leading_reference_column(rows, first_value_x, reference_x)

    anchors = []

    if has_leading_reference:
        anchors.append({"index": 0, "x": reference_x, "type": "code"})
        anchors.append({"index": 1, "x": None, "type": "label"})
    else:
        anchors.append({"index": 0, "x": None, "type": "label"})

        if _has_note_column(rows, value_columns):
            anchors.append({"index": 1, "x": reference_x, "type": "note"})

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


def _code_anchor(anchors):
    for anchor in anchors:
        if anchor["type"] == "code":
            return anchor
    return None


def _label_anchor_index(anchors):
    for anchor in anchors:
        if anchor["type"] == "label":
            return anchor["index"]
    return 0


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
    code_anchor = _code_anchor(anchors)
    label_index = _label_anchor_index(anchors)
    value_positions = _value_anchor_positions(anchors)

    if code_anchor and code_anchor["x"] is not None:
        code_corridor_left = max(0, code_anchor["x"] - 180)
        code_corridor_right = code_anchor["x"] + 170

        if (
            code_corridor_left <= center_x <= code_corridor_right
            and _is_reference_token(text)
            and not _word_is_part_of_period(word)
        ):
            return code_anchor["index"]

        if (
            row_is_header_like
            and code_corridor_left <= center_x <= code_corridor_right
            and _has_latin_alpha(text)
        ):
            return code_anchor["index"]

    # A hyphen inside an OCR source label line is punctuation, not a
    # financial dash value. Keep it in the label column. Standalone dash
    # values in real numeric areas still fall through to value assignment.
    if (
        text == "-"
        and _source_line_text(word)
        and not _line_text_has_amount(_source_line_text(word))
        and any(ch.isalpha() for ch in _source_line_text(word))
    ):
        return label_index

    if note_anchor and note_anchor["x"] is not None:
        note_corridor_left = max(0, note_anchor["x"] - 140)
        first_value_x = min(value_positions) if value_positions else None
        note_corridor_right = (
            first_value_x - 40
            if first_value_x is not None
            else note_anchor["x"] + 140
        )

        # Explicitly reserve the horizontal corridor between labels and the
        # first value column for compact note/reference tokens. This prevents
        # note numbers such as "12" or OCR variants like "3.12" from leaking
        # into financial value cells like "102.266".
        if (
            note_corridor_left <= center_x <= note_corridor_right
            and (
                is_small_note_reference(text)
                or lower in {"nota", "notas", "explicativa", "explicativas", "e"}
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

    # In recovered header rows, non-period text that sits over numeric value
    # columns should stay in its visual value column. This is geometry-based,
    # so labels such as "Último Exercício" are not hardcoded.
    if row_is_header_like and value_positions:
        nearest_value = min(value_positions, key=lambda pos: abs(center_x - pos))
        if abs(center_x - nearest_value) <= 260:
            return _nearest_anchor_index(center_x, anchors, allowed_types={"value"})

    # For all ordinary alphabetic content, keep Klippa-like row labels intact in
    # column 0. Do not split normal labels into several text columns.
    return label_index




def _clean_cell_content(content):
    content = content.strip()

    # If a wide placeholder dash was OCR'd immediately before a normal amount,
    # it can end up in the same value cell as "- 128.289". True negatives are
    # normalized earlier to "-128.289" with no space, so this removes only the
    # placeholder artifact.
    match = re.match(r"^-\s+(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)$", content)

    if match:
        return match.group(1)

    # Last-resort note/value cleanup after column assignment. If a compact
    # reference token was assigned into the first value cell together with a
    # financial amount, keep the financial amount and drop the reference.
    # Examples: "456 102.266" -> "102.266", "9 e 11 10.401" -> "10.401".
    # This deliberately only matches compact references followed by amount-like
    # values, so ordinary text cells and decimal values such as "R$ 0,80" are
    # not changed.
    match = re.match(
        r"^(?:\d{1,3}(?:\s+e\s+\d{1,3})?|\d{1,3}(?:\s+\d{1,3})+)\s+(-?\d{1,3}(?:[.]\d{3})+(?:,\d+)?|-?\d+,\d{2})$",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return content

# =========================================================
# matrix creation
# =========================================================

def _header_words_for_assignment(row, row_is_header_like):
    if not row_is_header_like:
        return row.get("words", [])

    words_by_line = defaultdict(list)

    for word in row.get("words", []):
        words_by_line[word.get("line_id")].append(word)

    assignment_words = []
    consumed_line_ids = set()

    for line_id, words in words_by_line.items():
        line_text = _source_line_text(words[0])

        if not line_text:
            continue

        if _line_text_has_amount(line_text):
            continue

        if not _has_latin_alpha(line_text):
            continue

        if _is_period_cell(line_text) or _is_period_cell(re.sub(r"\s+", "", line_text)):
            continue

        sorted_words = sorted(words, key=lambda w: w.get("x1", 0))
        average_x = sum(w.get("center_x", 0) for w in sorted_words) / len(sorted_words)

        line_span = max(w.get("x2", 0) for w in sorted_words) - min(w.get("x1", 0) for w in sorted_words)

        # Group full header lines mainly for value-column group labels and
        # compact left-side labels. If a left-side line spans both the
        # code/reference and label bands, keep individual words so geometry can
        # split them.
        if average_x < 1000 and len(sorted_words) > 2 and line_span > 380:
            continue

        assignment_words.append(
            {
                **sorted_words[0],
                "text": line_text,
                "x1": min(w.get("x1", 0) for w in sorted_words),
                "x2": max(w.get("x2", 0) for w in sorted_words),
                "center_x": average_x,
                "center_y": sum(w.get("center_y", 0) for w in sorted_words) / len(sorted_words),
            }
        )
        consumed_line_ids.add(line_id)

    for word in row.get("words", []):
        if word.get("line_id") not in consumed_line_ids:
            assignment_words.append(word)

    return sorted(assignment_words, key=lambda w: (w.get("center_y", 0), w.get("x1", 0)))


def rows_to_matrix(rows, numeric_columns=None):
    rows = normalize_financial_tokens_in_rows(rows)

    if numeric_columns is None:
        numeric_columns = detect_numeric_columns(rows)

    anchors = _build_column_anchors(rows, numeric_columns)
    column_count = max((a["index"] for a in anchors), default=0) + 1

    matrix = []

    for row in rows:
        row_cells = defaultdict(list)
        row_is_header_like = _row_is_header_like(row)

        for word in _header_words_for_assignment(row, row_is_header_like):
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

        if _label_anchor_index(anchors) == 0:
            row_cells = _restore_label_cells_from_source_lines(row, row_cells)

        for col in range(column_count):
            content = " ".join(row_cells.get(col, [])).strip()
            matrix_row.append(_clean_cell_content(content))

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

    if _is_metadata_title_text(text):
        return False

    return _row_amount_count(row) >= 1 or _row_period_count(row) >= 1


def _is_amount_cell(cell):
    value = (cell or "").strip()

    if not value or _is_period_cell(value):
        return False

    return bool(
        re.fullmatch(r"-?\(?\d{1,3}(?:[.]\d{3})+(?:,\d+)?\)?", value)
        or re.fullmatch(r"-?\(?\d+,\d{2}\)?", value)
        or (value.isdigit() and len(value) >= 1 and not _is_period_cell(value))
    )


def _row_amount_count(row):
    return sum(1 for cell in row if _is_amount_cell(cell))


def _row_period_count(row):
    return sum(1 for cell in row if _is_period_cell(cell))


def _row_is_header_candidate_matrix(row):
    row_text = " ".join(row).lower().strip()

    if not row_text or _is_metadata_title_text(row_text) or _is_footer_row(row):
        return False

    if _row_period_count(row) >= 1:
        return True

    if any(cell.strip() for cell in row) and _row_amount_count(row) == 0:
        return True

    return False


def _find_first_amount_row_index(matrix):
    for idx, row in enumerate(matrix):
        row_text = " ".join(row).lower().strip()

        if not row_text or _is_metadata_title_text(row_text) or _is_footer_row(row):
            continue

        if _row_amount_count(row) >= 1:
            return idx

    return None


def _find_table_start_index(matrix, first_amount_index):
    start_index = first_amount_index

    for idx in range(first_amount_index - 1, -1, -1):
        if not _row_is_header_candidate_matrix(matrix[idx]):
            break

        start_index = idx

    return start_index

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

    Exclude internal section totals such as ``Total do ativo circulante`` so
    the serializer does not prematurely close a table before later sections.
    """

    text = _normalize_text_for_matching(" ".join(row))

    if "total" not in text:
        return False

    section_terms = {
        "circulante",
        "nao circulante",
        "realizavel",
        "patrimonio liquido",
    }

    if any(term in text for term in section_terms):
        return False

    return any(term in text for term in FINAL_TOTAL_TERMS)


def filter_non_table_rows(matrix):
    """
    Klippa compatibility filter.

    Remove obvious page metadata before the table, but preserve the adjacent
    header block above the first body row. A table may therefore start with
    label-only or period rows before the first numeric amount row.
    """

    if not matrix:
        return []

    first_amount_index = _find_first_amount_row_index(matrix)

    if first_amount_index is None:
        return []

    start_index = _find_table_start_index(matrix, first_amount_index)

    filtered = []
    seen_numeric_table_row = False

    for row in matrix[start_index:]:
        row_text = " ".join(row).lower().strip()

        if _is_footer_row(row):
            break

        if "notas explicativas" in row_text and seen_numeric_table_row:
            break

        if "".join(row).strip() == "":
            continue

        filtered.append(row)

        if _row_amount_count(row) >= 1:
            seen_numeric_table_row = True

        # Strong final-total rows close the current visual table. This prevents
        # trailing signatures, certification text and footer fragments from being
        # serialized as extra table rows.
        if seen_numeric_table_row and _is_final_total_row(row):
            break

    return filtered

def _is_year_cell(cell):
    return _is_period_cell(cell)


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
        rows[0][0] = _join_nonempty(rows[0][0], rows[1][0])
        rows[1][0] = ""
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

        region_rows = normalize_financial_tokens_in_rows(region_rows)
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
