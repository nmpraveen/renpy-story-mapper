label start:
    menu:
        "Choose red":
            $ route = "red"
            $ love += 1
        "Choose blue":
            $ route = "blue"
            $ love += 2
    if route == "red":
        "Red follow-up."
    else:
        "Blue follow-up."
    return
