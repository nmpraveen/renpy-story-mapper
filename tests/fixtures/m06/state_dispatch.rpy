label start:
    menu:
        "Gain one point":
            $ love += 1
        "Gain two points":
            $ love += 2
    "The point detour reconverges."
    menu:
        "Choose red":
            $ route = "red"
        "Choose blue":
            $ route = "blue"
    if route == "red":
        jump red_route
    else:
        jump blue_route

label red_route:
    "Red follow-up."
    return

label blue_route:
    "Blue follow-up."
    return
