def compare_table_shapes(expected, generated):

    return {
        "expected_rows": expected.get("row_count"),
        "generated_rows": generated.get("row_count"),
        "expected_columns": expected.get("column_count"),
        "generated_columns": generated.get("column_count"),
    }
