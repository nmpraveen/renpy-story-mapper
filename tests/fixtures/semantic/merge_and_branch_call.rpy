label start:
    menu:
        "Take A":
            "Menu branch A."
        "Take B":
            "Menu branch B."
    "After menu."
    if flag_a:
        call helper
    elif flag_b:
        "Condition branch B."
    else:
        "Condition fallback."
    "After condition."
    return

label helper:
    "Inside helper."
    return
