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

        for line in lines:

            for word in line.get("Words", []):

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
                    }
                )

        pages.append(
            {
                "page_index": page_index,
                "words": words,
            }
        )

    return pages
