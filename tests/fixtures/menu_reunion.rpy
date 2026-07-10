label start:
    menu:
        narrator "Pick a route."
        "Take the left path":
            "Left."
        "Take the right path" if right_is_open:
            "Right."
    "Together again."
    return
