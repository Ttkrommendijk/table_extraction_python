import json


def load_ocrparse_json(path: str) -> dict:

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_words(ocr_json: dict) -> list:

    pages = []

    parsed_results = ocr_json.get("ParsedResults", [])

    for page_index, page in enumerate(parsed_results):

        overlay = page.get("Overlay", {})
        lines = overlay.get("Lines", [])

        words = []

        for line_index, line in enumerate(lines):

            line_text = line.get("LineText", "").strip()
            line_words = line.get("Words", [])
            line_id = f"{page_index}:{line_index}"

            for word_index, word in enumerate(line_words):

                left = word["Left"]
                top = word["Top"]
                width = word["Width"]
                height = word["Height"]

                words.append(
                    {
                        "text": word["WordText"].strip(),
                        "x1": left,
                        "y1": top,
                        "x2": left + width,
                        "y2": top + height,
                        "width": width,
                        "height": height,
                        "center_x": left + (width / 2),
                        "center_y": top + (height / 2),
                        # Preserve OCRParse line metadata. Some OCR engines already
                        # reconstruct the full visual text line correctly. Later
                        # layout stages may crop or split words by region, so keeping
                        # the original line lets us restore labels such as
                        # "Fornecedores - terrenos" when only the rightmost fragment
                        # survived the geometry split.
                        "line_id": line_id,
                        "line_index": line_index,
                        "line_word_index": word_index,
                        "line_text": line_text,
                    }
                )

        pages.append(
            {
                "page_index": page_index,
                "words": words,
            }
        )

    return pages
