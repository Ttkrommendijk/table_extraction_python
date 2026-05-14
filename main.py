import json
from pathlib import Path

from modules.klippa_serializer import (
    serialize_klippa_result_from_ocrparse,
    serialize_matrix_to_klippa_table,
)
from modules.ocrparse_loader import extract_words, load_ocrparse_json
from modules.row_builder import group_words_into_rows
from modules.table_matrix_builder import reconstruct_matrices_from_rows


def reconstruct_tables_from_page(page):
    rows = group_words_into_rows(page["words"])
    return reconstruct_matrices_from_rows(rows)


def build_klippa_result(ocrparse_json):
    pages = extract_words(ocrparse_json)
    tables = []

    for page in pages:
        matrices = reconstruct_tables_from_page(page)

        for matrix in matrices:
            table = serialize_matrix_to_klippa_table(
                matrix=matrix,
                document_index=page["page_index"],
            )

            tables.append(table)

    return serialize_klippa_result_from_ocrparse(tables, ocrparse_json)


def ask_input_file():
    while True:
        input_path = input("\nEnter OCRParse JSON path: ").strip()

        if not input_path:
            print("Path cannot be empty.")
            continue

        path = Path(input_path)

        if not path.exists():
            print(f"File not found: {path}")
            continue

        return path


def ask_output_file():
    output_path = input("\nEnter output JSON path: ").strip()

    if not output_path:
        output_path = "generated_klippa_result.json"

    return Path(output_path)


if __name__ == "__main__":
    print("\n=== TABLE EXTRACTION MVP ===")

    input_folder = Path("test_documents")
    output_folder = input_folder / "results"
    output_folder.mkdir(parents=True, exist_ok=True)

    input_files = sorted(input_folder.glob("*ocrparse.json"))

    if not input_files:
        print(f"\nNo files ending with ocrparse.json found in: {input_folder}")
        raise SystemExit(0)

    for input_file in input_files:
        print(f"\nProcessing: {input_file}")

        ocr_json = load_ocrparse_json(str(input_file))
        result = build_klippa_result(ocr_json)

        output_file = output_folder / f"{input_file.stem}_python_result.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(
                result,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print(f"Generated: {output_file}")

    print(f"\nDone. Processed {len(input_files)} file(s).")
