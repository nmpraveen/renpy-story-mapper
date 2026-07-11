label start:
    jump new_prologue

label new_prologue:
    "Rain covered the street."
    ian "I can help."
    scene bg street
    if ian_wits > 0:
        "Ian notices a clue."
    menu:
        "Offer help" if ian_charisma > 0:
            $ love += 1
            $ route_flag = "helper"
            jump ending
        "Walk away":
            $ money -= 10
            jump ending
    "One"
    "Two"
    "Three"
    "Four"
    "Five"
    "Six"
    "Seven"
    "Eight"
    "Nine"
    "Ten"
    "Eleven"
    "Twelve"
    "Thirteen"
    "Fourteen"

label ending:
    "The story ends."
    return
