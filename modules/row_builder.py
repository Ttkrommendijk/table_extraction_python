from modules.geometry import calculate_row_threshold


def group_words_into_rows(words: list) -> list:

    if not words:
        return []

    y_threshold = calculate_row_threshold(words)

    words_sorted = sorted(
        words,
        key=lambda w: w["center_y"],
    )

    rows = []

    for word in words_sorted:

        matched = False

        for row in rows:

            if abs(word["center_y"] - row["center_y"]) <= y_threshold:

                row["words"].append(word)

                centers = [
                    w["center_y"]
                    for w in row["words"]
                ]

                row["center_y"] = sum(centers) / len(centers)

                matched = True
                break

        if not matched:

            rows.append(
                {
                    "center_y": word["center_y"],
                    "words": [word],
                }
            )

    for row in rows:

        row["words"] = sorted(
            row["words"],
            key=lambda w: w["x1"],
        )

    return rows
