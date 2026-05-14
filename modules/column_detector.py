import re


NUMBER_REGEX = re.compile(
    r"""
    ^
    \(?
    -?
    \d{1,3}
    (?:[\.,]\d{3})*
    (?:[\.,]\d+)?
    \)?
    $
    """,
    re.VERBOSE,
)


HEADER_WORDS = {
    "nota",
    "notas",
    "2025",
    "2024",
    "2023",
    "2022",
    "31/07/2025",
    "31/12/2024",
    "31/12/2023",
    "31/12/2022",
}


def is_numeric(text: str) -> bool:

    text = text.strip()

    if text == "-":
        return True

    return bool(NUMBER_REGEX.match(text))


def is_small_note_reference(text: str) -> bool:

    text = text.strip()

    return text.isdigit() and len(text) <= 2


def cluster_positions(positions, threshold=140):

    if not positions:
        return []

    positions = sorted(positions)
    clusters = []

    for position in positions:

        matched = False

        for cluster in clusters:

            avg = sum(cluster) / len(cluster)

            if abs(position - avg) <= threshold:
                cluster.append(position)
                matched = True
                break

        if not matched:
            clusters.append([position])

    return [sum(cluster) / len(cluster) for cluster in clusters]


def detect_numeric_columns(rows: list, include_note_references=False) -> list:
    """
    Detect visual numeric/value columns from row geometry.

    Very sparse numeric-looking columns are ignored. In financial statements a
    note reference can sometimes be OCR'd as something like ``3.12``; without
    this support check that single token becomes a false value column and shifts
    all real amount columns to the right.
    """

    numeric_centers = []

    for row in rows:
        for word in row.get("words", []):
            text = word["text"].strip()

            # A standalone dash can be a real empty/zero amount, but it is
            # too ambiguous to create a numeric column. In labels such as
            # "Fornecedores - terrenos" it otherwise creates a false value
            # column before the real note/reference column. Existing amount
            # columns will still receive dash tokens during word assignment.
            if text == "-":
                continue

            if not include_note_references and is_small_note_reference(text):
                continue

            if is_numeric(text):
                numeric_centers.append(word["center_x"])

    columns = cluster_positions(
        numeric_centers,
        threshold=140,
    )

    supported_columns = []

    for center in columns:
        support_rows = 0

        for row in rows:
            row_has_supported_value = False

            for word in row.get("words", []):
                text = word["text"].strip()

                if text == "-":
                    continue

                if not include_note_references and is_small_note_reference(text):
                    continue

                if is_numeric(text) and abs(word["center_x"] - center) <= 140:
                    row_has_supported_value = True
                    break

            if row_has_supported_value:
                support_rows += 1

        if support_rows >= 2:
            supported_columns.append(center)

    # Avoid returning nothing for tiny/simple tables.
    if not supported_columns and columns:
        supported_columns = columns

    return [
        {
            "index": idx,
            "x": center,
        }
        for idx, center in enumerate(supported_columns)
    ]
