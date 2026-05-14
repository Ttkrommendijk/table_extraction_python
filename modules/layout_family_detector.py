
def detect_layout_family(rows, numeric_columns):

    numeric_count = len(numeric_columns)

    max_numbers_per_row = 0

    for row in rows:

        numeric_in_row = 0

        for word in row["words"]:

            text = word["text"]

            if any(ch.isdigit() for ch in text):
                numeric_in_row += 1

        max_numbers_per_row = max(
            max_numbers_per_row,
            numeric_in_row,
        )

    if numeric_count <= 1:
        return "two_column"

    if numeric_count == 2:
        return "standard_4col"

    if numeric_count >= 4:
        return "multi_entity"

    return "generic"
