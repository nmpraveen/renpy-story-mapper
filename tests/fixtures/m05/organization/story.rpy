label start:
    "A storm begins."
    if courage > 0:
        "The door opens."
    menu:
        "Enter":
            $ trust += 1
            jump ending
        "Leave":
            $ route = "home"
            jump ending

label ending:
    "The paths meet."
    return
