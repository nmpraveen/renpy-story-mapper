label start:
    scene room
    "Before the choice."
    menu:
        "Left":
            jump next_room
        "Right":
            jump next_room

label next_room:
    scene next_room
    "After the rejoin."
    return
