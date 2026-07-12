label start:
    menu:
        "Short left":
            "Left."
        "Short right":
            "Right."
    "The short routes merge."

    if optional_scene:
        "This scene can be bypassed."
    "The bypass merges."

    menu:
        "Long left":
            "Left one."
            "Left two."
            "Left three."
            "Left four."
            "Left five."
            "Left six."
            "Left seven."
            "Left eight."
        "Long right":
            "Right one."
            "Right two."
            "Right three."
            "Right four."
            "Right five."
            "Right six."
            "Right seven."
            "Right eight."
    "The long routes merge."
    return

label terminal_routes:
    menu:
        "Ending A":
            jump ending_a
        "Ending B":
            jump ending_b

label ending_a:
    "A."
    return

label ending_b:
    "B."
    return

label shared_routes:
    menu:
        "Shared A":
            jump shared_ending
        "Shared B":
            jump shared_ending

label shared_ending:
    "Shared."
    return
