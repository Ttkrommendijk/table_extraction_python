def identify_low_confidence_rows(matrix):

    low_confidence_rows = []

    for idx, row in enumerate(matrix):

        empty_count = row.count("")

        if empty_count > (len(row) / 2):

            low_confidence_rows.append(
                {
                    "row_index": idx,
                    "row": row,
                }
            )

    return low_confidence_rows
