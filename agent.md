#repsonsabilities of files in modules folder
ocrparse_loader.py
reads OCRParse JSON and converts it to normalized words

geometry.py
shared helpers: bounding boxes, centers, thresholds

row_builder.py
groups words into visual rows

column_detector.py
detects note, year and numeric columns

table_matrix_builder.py
turns rows and columns into a table matrix

klippa_serializer.py
converts the matrix into Klippa compatible JSON

validation.py
compares generated result against Klippa golden result

llm_repair.py
later fallback for low confidence rows
