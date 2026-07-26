default resolve_points = 0

label start:
    scene atrium
    "The travelers arrive at the atrium."
    menu:
        "Pause at the fountain":
            "They take a short fountain detour."
            jump after_fountain
        "Continue through the atrium":
            "They stay on the direct route."

            jump after_fountain

label after_fountain:
    scene corridor
    "The fountain paths rejoin before the next decision."
    menu:
        "Take the marked passage":
            "The marked passage leads toward tomorrow."
            jump day_two
        "Explore the side passage":
            "They enter the alternate passage."
            menu:
                "Return to the marked passage":
                    "They turn back toward tomorrow."
                    jump day_two
                "Open the old gate":
                    $ resolve_points += 1
                    "They reach the deepest chamber."
                    jump day_two

label day_two:
    scene overlook
    "The travelers reunite at the next-day overlook."
    return
