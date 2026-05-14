from modules.column_detector import is_numeric, is_small_note_reference, cluster_positions


TABLE_START_KEYWORDS = {
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

TABLE_END_KEYWORDS = {
    "reconhecemos",
    "assinado",
    "assinatura",
    "cpf:",
    "cnpj/cpf",
    "crc",
    "avenida",
    "pabx",
    "www.",
}


def _row_text(row):
    return " ".join(w["text"] for w in row.get("words", [])).strip()


def _row_text_lower(row):
    return _row_text(row).lower()


def _row_has_number(row):
    return any(is_numeric(w["text"].strip()) for w in row.get("words", []))


def _row_has_alpha(row):
    return any(any(ch.isalpha() for ch in w["text"]) for w in row.get("words", []))


def _is_value_word(word):
    text = word["text"].strip()

    if is_small_note_reference(text):
        return False

    return is_numeric(text)


def _is_alpha_word(word):
    return any(ch.isalpha() for ch in word["text"])


def _clone_row_with_words(row, words):
    words = sorted(words, key=lambda w: w["x1"])

    if words:
        center_y = sum(w["center_y"] for w in words) / len(words)
    else:
        center_y = row.get("center_y", 0)

    return {
        "center_y": center_y,
        "words": words,
    }


def _looks_like_start(row):
    text = _row_text_lower(row)
    return any(keyword in text for keyword in TABLE_START_KEYWORDS)


def _looks_like_end(row):
    text = _row_text_lower(row)
    return any(keyword in text for keyword in TABLE_END_KEYWORDS)


def crop_table_region_rows(rows):
    """
    Light Klippa-compatible crop.

    Keep table headers, section rows, subtotal rows and sparse rows. Remove only
    pre-table material and obvious signature/footer narrative after the table.
    """

    if not rows:
        return []

    start_index = 0

    for idx, row in enumerate(rows):
        if _looks_like_start(row):
            start_index = idx
            break

    cropped = []
    seen_table_number = False

    for row in rows[start_index:]:
        text = _row_text_lower(row)

        if _looks_like_end(row):
            break

        if "notas explicativas" in text and seen_table_number:
            break

        if _row_has_number(row):
            seen_table_number = True

        cropped.append(row)

    return cropped


def _region_has_table_content(rows):
    if len(rows) < 2:
        return False

    numeric_rows = sum(1 for row in rows if _row_has_number(row))
    alpha_rows = sum(1 for row in rows if _row_has_alpha(row))

    return numeric_rows >= 2 and alpha_rows >= 2


def _candidate_rows_for_region_detection(rows):
    cropped = crop_table_region_rows(rows)

    if cropped:
        return cropped

    return rows


def _detect_value_columns(rows):
    centers = []

    for row in rows:
        for word in row.get("words", []):
            if _is_value_word(word):
                centers.append(word["center_x"])

    return cluster_positions(
        centers,
        threshold=140,
    )


def _count_rows_with_alpha_between_value_columns(rows, left_value_x, right_value_x):
    count = 0

    for row in rows:
        has_left_value = False
        has_right_value = False
        has_middle_alpha = False

        for word in row.get("words", []):
            text = word["text"].strip()
            x = word["center_x"]

            if is_numeric(text):
                if abs(x - left_value_x) <= 220:
                    has_left_value = True
                if abs(x - right_value_x) <= 220:
                    has_right_value = True
            elif left_value_x + 60 < x < right_value_x - 60 and _is_alpha_word(word):
                has_middle_alpha = True

        if has_middle_alpha and (has_left_value or has_right_value):
            count += 1

    return count


def should_split_side_by_side(rows):
    """
    Detect generic side-by-side visual tables:

    label | values     label | values

    This is intentionally based on repeated geometry, not file names or company
    names. It is used only before grid reconstruction.
    """

    analysis_rows = _candidate_rows_for_region_detection(rows)
    value_columns = _detect_value_columns(analysis_rows)

    if len(value_columns) < 2:
        return False

    for left_x, right_x in zip(value_columns, value_columns[1:]):
        count = _count_rows_with_alpha_between_value_columns(
            analysis_rows,
            left_x,
            right_x,
        )

        if count >= 3:
            return True

    return False


def _find_best_split_x(rows):
    """
    Find the cut line just before the right-side label band.

    We choose the left edge of the repeated middle label band rather than a
    fixed page midpoint. This keeps the rule generic across side-by-side forms.
    """

    analysis_rows = _candidate_rows_for_region_detection(rows)
    value_columns = _detect_value_columns(analysis_rows)

    best_split = None
    best_score = -1

    for left_x, right_x in zip(value_columns, value_columns[1:]):
        middle_label_left_edges = []

        for row in analysis_rows:
            has_left_value = False
            has_right_value = False

            for word in row.get("words", []):
                text = word["text"].strip()
                x = word["center_x"]

                if is_numeric(text) and abs(x - left_x) <= 220:
                    has_left_value = True

                if is_numeric(text) and abs(x - right_x) <= 220:
                    has_right_value = True

            if not (has_left_value or has_right_value):
                continue

            for word in row.get("words", []):
                x = word["center_x"]

                if left_x + 60 < x < right_x - 60 and _is_alpha_word(word):
                    middle_label_left_edges.append(word["x1"])

        if not middle_label_left_edges:
            continue

        split_x = min(middle_label_left_edges) - 20

        score = _count_rows_with_alpha_between_value_columns(
            analysis_rows,
            left_x,
            right_x,
        )

        if score > best_score:
            best_score = score
            best_split = split_x

    return best_split


def split_side_by_side_regions(rows):
    """
    Return independent visual table regions. If no strong split is detected,
    return one lightly cropped region.
    """

    if not should_split_side_by_side(rows):
        return [crop_table_region_rows(rows)]

    split_x = _find_best_split_x(rows)

    if split_x is None:
        return [crop_table_region_rows(rows)]

    left_rows = []
    right_rows = []

    for row in rows:
        left_words = []
        right_words = []

        for word in row.get("words", []):
            if word["center_x"] < split_x:
                left_words.append(word)
            else:
                right_words.append(word)

        if left_words:
            left_rows.append(_clone_row_with_words(row, left_words))

        if right_words:
            right_rows.append(_clone_row_with_words(row, right_words))

    regions = []

    for region_rows in [left_rows, right_rows]:
        cropped = crop_table_region_rows(region_rows)

        if _region_has_table_content(cropped):
            regions.append(cropped)

    return regions or [crop_table_region_rows(rows)]


TITLE_TERMS = {
    "demonstração",
    "demonstracao",
    "resultado do exercício",
    "resultado do exercicio",
    "unidades de reais",
    "em milhares",
}


def classify_row(row):
    text = _row_text_lower(row)

    if not text:
        return "empty"

    if any(term in text for term in TABLE_END_KEYWORDS):
        return "footer"

    if any(term in text for term in TITLE_TERMS):
        return "title"

    if _row_has_number(row):
        return "data"

    if any(term in text for term in TABLE_START_KEYWORDS):
        return "header"

    return "section"


def detect_table_regions(rows):
    regions=[]
    current=[]
    started=False

    for row in rows:
        row_type=classify_row(row)

        if row_type in {"footer"}:
            if current:
                regions.append(current)
                current=[]
            started=False
            continue

        if row_type in {"header","data","section"}:
            started=True

        if not started:
            continue

        if row_type=="title" and current:
            continue

        current.append(row)

    if current:
        regions.append(current)

    return [r for r in regions if _region_has_table_content(r)]
