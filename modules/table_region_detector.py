import re

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


def _is_period_like(text):
    """Detect generic reporting-period tokens without hardcoded years.

    Supported examples include 2025, 31/12/2025, 12/2025, jan/2025,
    janeiro 2025 and similar month/year or day/month/year variants.
    """

    value = (text or "").strip().lower()

    if not value:
        return False

    # Accept period headers with a restatement/qualifier suffix, e.g.
    # "2022 (Reapresentado)". The period is still the structural anchor.
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()

    if re.fullmatch(r"(?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", value):
        return True

    if re.fullmatch(r"\d{1,2}[/-](?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"[a-zçãáàâéêíóôõú]{3,12}[/-](?:19|20)\d{2}", value):
        return True

    if re.fullmatch(r"[a-zçãáàâéêíóôõú]{3,12}\s+(?:19|20)\d{2}", value):
        return True

    return False


def _row_has_period_like_token(row):
    return any(_is_period_like(w.get("text", "")) for w in row.get("words", []))


def _row_value_count(row):
    return sum(1 for word in row.get("words", []) if _is_value_word(word))


def _looks_like_body_row(row):
    return _row_has_alpha(row) and _row_value_count(row) >= 1


def _looks_like_header_candidate(row):
    words = row.get("words", [])

    if not words:
        return False

    if _looks_like_end(row):
        return False

    # Header rows are usually label-only rows, period rows, or rows with
    # sparse structure immediately above the first repeated value row. This is
    # intentionally geometric/pattern-based, not vocabulary-based.
    if _row_has_period_like_token(row):
        return True

    if _row_has_alpha(row) and _row_value_count(row) <= 1:
        return True

    return False


def _recover_header_start_index(rows, first_body_index):
    """Include visually adjacent header rows above the first body row.

    The first body row is found by repeated table geometry. Rows above it are
    included when they are close enough and look like column headers or period
    rows. This handles multi-line headers such as a left column label split into
    two OCR lines, while still excluding page titles and unit lines higher up.
    """

    if first_body_index <= 0:
        return first_body_index

    median_gap = _median_row_gap(rows) or 60
    max_header_gap = max(90, median_gap * 1.8)
    start_index = first_body_index
    previous_y = rows[first_body_index].get("center_y", 0)

    for idx in range(first_body_index - 1, -1, -1):
        row = rows[idx]
        row_y = row.get("center_y", 0)
        gap = previous_y - row_y

        if gap > max_header_gap:
            break

        if not _looks_like_header_candidate(row):
            break

        start_index = idx
        previous_y = row_y

    return start_index


def _row_amount_centers(row):
    return [
        word["center_x"]
        for word in row.get("words", [])
        if _is_value_word(word)
    ]


def _row_looks_like_page_metadata(row):
    """Return True for document titles/metadata that should not start a table.

    This is intentionally structural. Metadata rows often sit above the visual
    table, contain many words, and either have no repeated value columns or have
    identifiers/dates embedded in prose. They should not be allowed to become
    the first body row, otherwise header recovery starts too high and side by
    side detection can split normal value columns.
    """

    text = _row_text_lower(row).strip()

    if not text:
        return True

    metadata_terms = {
        "cnpj",
        "exercícios findos",
        "exercicios findos",
        "milhares de reais",
        "em milhares",
        "unidades de reais",
    }

    if any(term in text for term in metadata_terms):
        return True

    words = row.get("words", [])
    alpha_words = sum(1 for word in words if _is_alpha_word(word))
    value_words = sum(1 for word in words if _is_value_word(word))

    # Long text-only title rows are not table body rows.
    if alpha_words >= 2 and value_words == 0 and len(words) >= 3:
        return True

    return False


def _has_following_aligned_body_rows(rows, start_index, reference_centers):
    if not reference_centers:
        return False

    matches = 0

    for row in rows[start_index + 1:start_index + 8]:
        if _row_looks_like_page_metadata(row) or _looks_like_end(row):
            continue

        centers = _row_amount_centers(row)

        if not centers:
            continue

        matched_centers = 0
        for center in centers:
            if any(abs(center - reference) <= 180 for reference in reference_centers):
                matched_centers += 1

        if matched_centers >= min(1, len(reference_centers)) and _row_has_alpha(row):
            matches += 1

        if matches >= 2:
            return True

    return False


def _find_first_body_index(rows):
    for idx, row in enumerate(rows):
        text = _row_text_lower(row).strip()

        if not text or _looks_like_end(row) or _row_looks_like_page_metadata(row):
            continue

        centers = _row_amount_centers(row)

        # Prefer rows that already show at least two value columns. This is the
        # strongest generic signal for a financial table body row.
        if _row_has_alpha(row) and len(centers) >= 2:
            return idx

        # Some statements only have one populated amount in the first body row.
        # Accept it only when following rows repeat the same value-column
        # geometry, preventing metadata identifiers from starting the table.
        if _row_has_alpha(row) and len(centers) == 1:
            if _has_following_aligned_body_rows(rows, idx, centers):
                return idx

    for idx, row in enumerate(rows):
        if _row_has_number(row) and not _row_looks_like_page_metadata(row):
            return idx

    return 0


def _is_value_word(word):
    text = word["text"].strip()

    # Standalone dashes are too ambiguous for region splitting. In labels such
    # as "Impostos sobre a renda - corrente" they can otherwise create a false
    # value column and trigger an invalid side-by-side split.
    if text == "-":
        return False

    if is_small_note_reference(text):
        return False

    return is_numeric(text)


def _is_currency_marker_word(word):
    text = word["text"].strip().upper().replace(" ", "")
    return text in {"R", "$", "R$", "RS", "_R", "_R$"}


def _is_alpha_word(word):
    return any(ch.isalpha() for ch in word["text"])


def _is_split_label_word(word):
    """Return True for alpha tokens that can indicate a right-side label band.

    Side-by-side table detection looks for repeated alphabetic text between
    value columns. Currency markers such as R, R$, and RS are alphabetic but
    are part of money values, not labels. Treating them as labels can split a
    normal table between Saldo Inicial and Saldo Final.
    """
    return _is_alpha_word(word) and not _is_currency_marker_word(word)


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
    text = _row_text_lower(row).strip()

    # Page titles like "Demonstração dos resultados" and date/unit lines are
    # not table starts. Starting there pollutes value-column detection and can
    # trigger a false side-by-side split on DRE pages.
    title_terms = {
        "resultados",
        "resultado",
        "demonstração dos resultados",
        "demonstracao dos resultados",
        "demonstração do resultado",
        "demonstracao do resultado",
        "exercícios findos",
        "exercicios findos",
        "milhares de reais",
        "unidades de reais",
    }

    if not text:
        return False

    if text in title_terms or any(term in text for term in title_terms if len(term) > 10):
        return False

    return any(keyword in text for keyword in TABLE_START_KEYWORDS)


def _looks_like_end(row):
    text = _row_text_lower(row)
    return any(keyword in text for keyword in TABLE_END_KEYWORDS)


def crop_table_region_rows(rows):
    """Light Klippa-compatible crop.

    Keep the visual table header block plus body rows. The table start is
    determined by first finding the first body row and then walking upward to
    recover adjacent header rows. This prevents multi-line headers from being
    discarded just because they do not themselves contain amounts.
    """

    if not rows:
        return []

    first_body_index = _find_first_body_index(rows)
    start_index = _recover_header_start_index(rows, first_body_index)

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
            elif left_value_x + 60 < x < right_value_x - 60 and _is_split_label_word(word):
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

                if left_x + 60 < x < right_x - 60 and _is_split_label_word(word):
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
        return _split_after_final_total_restarts(crop_table_region_rows(rows))

    split_x = _find_best_split_x(rows)

    if split_x is None:
        return _split_after_final_total_restarts(crop_table_region_rows(rows))

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

    return regions or _split_after_final_total_restarts(crop_table_region_rows(rows))


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

    normalized = (text or "").lower()

    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    return " ".join(normalized.split())


def _is_strong_final_total_row(row):
    """Return True only for table-closing totals, not section subtotals.

    This deliberately excludes labels such as ``Total do ativo circulante``
    because those are internal section totals. It is used only to create a
    possible vertical table boundary before the matrix serializer applies its
    normal row filtering.
    """

    text = _normalize_text_for_matching(_row_text(row))

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

    return (
        "total do ativo" in text
        or "total ativo" in text
        or "total do passivo" in text
        or "total passivo" in text
    )


def _median_row_gap(rows):
    gaps = []

    previous_y = None
    for row in rows:
        y = row.get("center_y", 0)
        if previous_y is not None:
            gap = y - previous_y
            if gap > 0:
                gaps.append(gap)
        previous_y = y

    if not gaps:
        return 0

    gaps = sorted(gaps)
    return gaps[len(gaps) // 2]


def _row_value_centers(row):
    return [
        word["center_x"]
        for word in row.get("words", [])
        if _is_value_word(word)
    ]


def _columns_roughly_match(candidate_centers, reference_centers, tolerance=180):
    if not candidate_centers or not reference_centers:
        return False

    matches = 0
    for candidate in candidate_centers:
        if any(abs(candidate - reference) <= tolerance for reference in reference_centers):
            matches += 1

    return matches >= min(2, len(reference_centers), len(candidate_centers))


def _has_following_aligned_numeric_block(rows, start_index, reference_centers):
    numeric_rows = 0
    alpha_rows = 0

    for row in rows[start_index:start_index + 10]:
        text = _row_text_lower(row)
        if _looks_like_end(row) or "notas explicativas" in text:
            break

        centers = _row_value_centers(row)

        if centers and _columns_roughly_match(centers, reference_centers):
            numeric_rows += 1

        if _row_has_alpha(row):
            alpha_rows += 1

    return numeric_rows >= 2 and alpha_rows >= 2


def _split_after_final_total_restarts(rows):
    """Split stacked tables after a strong final total when layout restarts.

    Low-risk geometry rule:
    after a strong final total, if a later label-only row is followed by
    multiple rows whose numeric columns match the prior table, treat that as a
    new stacked table region. No label words such as Ativo/Passivo/DRE are used
    as anchors.
    """

    if len(rows) < 4:
        return [rows]

    median_gap = _median_row_gap(rows)
    regions = []
    start = 0

    idx = 0
    while idx < len(rows):
        row = rows[idx]

        if not _is_strong_final_total_row(row):
            idx += 1
            continue

        reference_centers = _row_value_centers(row)
        if len(reference_centers) < 2:
            idx += 1
            continue

        split_index = None

        for probe in range(idx + 1, min(len(rows), idx + 6)):
            gap = rows[probe].get("center_y", 0) - row.get("center_y", 0)
            if median_gap and gap < median_gap * 3.0:
                continue

            if _row_has_number(rows[probe]):
                continue

            if not _row_has_alpha(rows[probe]):
                continue

            if _has_following_aligned_numeric_block(rows, probe + 1, reference_centers):
                split_index = probe
                break

        if split_index is not None:
            before = rows[start:split_index]
            if _region_has_table_content(before):
                regions.append(before)
            start = split_index
            idx = split_index + 1
            continue

        idx += 1

    tail = rows[start:]
    if _region_has_table_content(tail):
        regions.append(tail)

    return regions or [rows]


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
