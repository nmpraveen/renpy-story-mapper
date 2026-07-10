label gated_route:
    if wits > 0 and chapter >= 2:
        "The skilled route opens."
    elif 0 < charisma <= 5:
        "The charm route opens."
    else:
        "No stat route opens."

    menu:
        "Take the paid date" if money >= 10 and (dating or love > 2):
            $ money -= 10
            $ route_love += 1
        "Stay faithful" if not cheating and dating:
            $ relationship_flag = "committed"
    return
