import copy
import re


_ACCOUNTING_NUMBER_RE = re.compile(
    r"""
    ^
    -?
    \d{1,3}
    (?:[\.,]\d{3})*
    (?:[\.,]\d+)?
    $
    """,
    re.VERBOSE,
)


OPEN_PAREN_TOKENS = {"(", "（"}
CLOSE_PAREN_TOKENS = {")",
    "）",
}
MINUS_TOKENS = {"-", "−", "–", "—"}


def _clean_text(text):
    return (text or "").strip()


def _is_accounting_number(text):
    text = _clean_text(text)
    return bool(_ACCOUNTING_NUMBER_RE.match(text))


def _is_parenthesized_accounting_number(text):
    text = _clean_text(text).replace(" ", "")
    return (
        len(text) >= 3
        and text[0] in OPEN_PAREN_TOKENS
        and text[-1] in CLOSE_PAREN_TOKENS
        and _is_accounting_number(text[1:-1])
    )


def _is_trailing_minus_number(text):
    text = _clean_text(text).replace(" ", "")
    return len(text) >= 2 and text[-1] in MINUS_TOKENS and _is_accounting_number(text[:-1])


def _copy_as_negative_number(word, number_text, source_words):
    normalized = copy.deepcopy(word)
    normalized["text"] = f"-{number_text.lstrip('-')}"
    normalized["x1"] = min(w.get("x1", w.get("center_x", 0)) for w in source_words)
    normalized["y1"] = min(w.get("y1", w.get("center_y", 0)) for w in source_words)
    normalized["x2"] = max(w.get("x2", w.get("center_x", 0)) for w in source_words)
    normalized["y2"] = max(w.get("y2", w.get("center_y", 0)) for w in source_words)
    normalized["width"] = normalized["x2"] - normalized["x1"]
    normalized["height"] = normalized["y2"] - normalized["y1"]
    normalized["center_x"] = normalized["x1"] + (normalized["width"] / 2)
    normalized["center_y"] = normalized["y1"] + (normalized["height"] / 2)
    normalized["financial_token_normalized"] = True
    normalized["source_texts"] = [_clean_text(w.get("text", "")) for w in source_words]
    return normalized


def _normalize_word_if_single_token_negative(word):
    text = _clean_text(word.get("text", ""))
    compact = text.replace(" ", "")

    if _is_parenthesized_accounting_number(compact):
        number_text = compact[1:-1]
        return _copy_as_negative_number(word, number_text, [word])

    if _is_trailing_minus_number(compact):
        number_text = compact[:-1]
        return _copy_as_negative_number(word, number_text, [word])

    return copy.deepcopy(word)


def _same_visual_line(a, b, y_tolerance):
    return abs(a.get("center_y", 0) - b.get("center_y", 0)) <= y_tolerance


def _horizontal_gap(left_word, right_word):
    return right_word.get("x1", right_word.get("center_x", 0)) - left_word.get("x2", left_word.get("center_x", 0))


def _close_horizontally(left_word, right_word, max_gap):
    return _horizontal_gap(left_word, right_word) <= max_gap


def normalize_financial_tokens_in_row(row):
    """Merge visual accounting negatives before column assignment.

    This is geometry-only: it uses same-row baseline proximity and horizontal
    proximity to combine OCR fragments such as ``(``, ``394.105``, ``)`` into a
    single ``-394.105`` token. Standalone parentheses used around non-numeric
    labels are left untouched.
    """

    row_copy = copy.deepcopy(row)
    words = sorted(row_copy.get("words", []), key=lambda w: w.get("x1", 0))

    if not words:
        row_copy["words"] = []
        return row_copy

    median_height = sorted(w.get("height", 0) for w in words)[len(words) // 2] or 1
    y_tolerance = max(4, median_height * 0.45)
    max_gap = max(10, median_height * 0.9)
    # A standalone dash in a financial table is often a placeholder for an
    # empty/zero value. Use a much stricter threshold when interpreting a dash
    # as a sign so placeholders between columns do not become false negatives.
    max_negative_sign_gap = max(4, median_height * 0.25)

    normalized_words = []
    i = 0

    while i < len(words):
        current = words[i]
        text = _clean_text(current.get("text", ""))

        if text in OPEN_PAREN_TOKENS and i + 2 < len(words):
            number_word = words[i + 1]
            close_word = words[i + 2]
            number_text = _clean_text(number_word.get("text", ""))
            close_text = _clean_text(close_word.get("text", ""))

            if (
                _same_visual_line(current, number_word, y_tolerance)
                and _same_visual_line(number_word, close_word, y_tolerance)
                and _close_horizontally(current, number_word, max_gap)
                and _close_horizontally(number_word, close_word, max_gap)
                and close_text in CLOSE_PAREN_TOKENS
                and _is_accounting_number(number_text)
            ):
                normalized_words.append(
                    _copy_as_negative_number(number_word, number_text, [current, number_word, close_word])
                )
                i += 3
                continue

        if text in MINUS_TOKENS and i + 1 < len(words):
            number_word = words[i + 1]
            number_text = _clean_text(number_word.get("text", ""))

            if (
                _same_visual_line(current, number_word, y_tolerance)
                and current.get("width", 0) <= median_height * 0.7
                and _close_horizontally(current, number_word, max_negative_sign_gap)
                and _is_accounting_number(number_text)
            ):
                normalized_words.append(
                    _copy_as_negative_number(number_word, number_text, [current, number_word])
                )
                i += 2
                continue

        normalized_words.append(_normalize_word_if_single_token_negative(current))
        i += 1

    row_copy["words"] = sorted(normalized_words, key=lambda w: w.get("x1", 0))
    return row_copy


def normalize_financial_tokens_in_rows(rows):
    return [normalize_financial_tokens_in_row(row) for row in rows]
