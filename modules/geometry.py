from statistics import median


ROW_Y_THRESHOLD_MULTIPLIER = 0.6


def calculate_row_threshold(words):

    heights = [w["height"] for w in words]

    return median(heights) * ROW_Y_THRESHOLD_MULTIPLIER
