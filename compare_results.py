import json
import sys
from collections import Counter
from pathlib import Path


def load_tables(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("ocr_result_klippa", {}).get("components", {}).get("tables", {}).get("tables", [])


def table_signature(table):
    cells = table.get("cells", [])
    content = [c.get("content", "").strip() for c in cells if c.get("content", "").strip()]

    return Counter(content)


def compare(expected_path, generated_path):
    expected = load_tables(expected_path)
    generated = load_tables(generated_path)

    print("table_count")
    print(f"  expected:  {len(expected)}")
    print(f"  generated: {len(generated)}")
    print()

    max_len = max(len(expected), len(generated))

    for idx in range(max_len):
        print(f"table {idx}")

        if idx >= len(expected):
            print("  extra generated table")
            continue

        if idx >= len(generated):
            print("  missing generated table")
            continue

        exp = expected[idx]
        gen = generated[idx]

        print(f"  rows:    expected {exp.get('row_count')} / generated {gen.get('row_count')}")
        print(f"  columns: expected {exp.get('column_count')} / generated {gen.get('column_count')}")

        exp_sig = table_signature(exp)
        gen_sig = table_signature(gen)

        common = sum((exp_sig & gen_sig).values())
        exp_total = sum(exp_sig.values())
        gen_total = sum(gen_sig.values())

        recall = common / exp_total if exp_total else 0
        precision = common / gen_total if gen_total else 0

        print(f"  content recall:    {recall:.2%}")
        print(f"  content precision: {precision:.2%}")

        missing = list((exp_sig - gen_sig).elements())[:10]
        extra = list((gen_sig - exp_sig).elements())[:10]

        if missing:
            print("  sample missing:")
            for item in missing:
                print(f"    - {item}")

        if extra:
            print("  sample extra:")
            for item in extra:
                print(f"    + {item}")

        print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        script = Path(sys.argv[0]).name
        print(f"Usage: python {script} expected_klippa.json generated.json")
        sys.exit(1)

    compare(sys.argv[1], sys.argv[2])
