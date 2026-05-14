import base64
import os

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = os.path.abspath(os.path.join(MODULE_DIR, "..", ".."))

TEST_DOCUMENTS_DIR = os.path.join(PROJECT_ROOT, "test_documents")


def pdf_to_base64(file_name):
    """
    Converts a PDF file from the test_documents folder to Base64
    and creates a .base64 file in the same folder.
    """

    pdf_path = os.path.join(TEST_DOCUMENTS_DIR, file_name)

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    with open(pdf_path, "rb") as pdf_file:
        encoded_string = base64.b64encode(pdf_file.read()).decode("utf-8")

    output_file = f"{pdf_path}.base64"

    with open(output_file, "w", encoding="utf-8") as output:
        output.write(encoded_string)

    return output_file


if __name__ == "__main__":
    file_name = input("Enter the PDF file name: ").strip()

    try:
        result = pdf_to_base64(file_name)
        print(f"Base64 file created successfully:")
        print(result)

    except Exception as e:
        print(f"Error: {e}")
