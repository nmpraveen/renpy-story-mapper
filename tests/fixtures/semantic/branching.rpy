label start:
    menu:
        "Take the lit path" if lantern:
            "The stones shine."
        "Wait":
            "Time passes."
    if courage > 5:
        call helper
    elif courage == 5:
        jump ending
    else:
        "Not yet."
    "The paths meet."
    jump ending

label helper:
    "A shared warning."
    return

label ending:
    "The end."
    return
