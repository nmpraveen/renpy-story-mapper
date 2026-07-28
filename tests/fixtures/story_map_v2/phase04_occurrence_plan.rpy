label early_ending:
    "The ending is defined before the story begins."
    return

label shared_memory:
    scene memory
    "The same memory is visited from two call sites."
    return

label start:
    scene opening
    "The story begins after physically earlier definitions."
    call shared_memory
    "The first call returns to the opening."
    call shared_memory
    "The second call returns to the opening."

    menu:
        "Explore locally":
            menu:
                "Take the known turn":
                    "The known nested route stays local."
                "Take the uncertain turn" if dynamic_gate():
                    "The unresolved nested route stays visible."
        "Continue directly":
            "The direct local arm stays visible."
    "The nested local choice rejoins once."
    jump route_gate

label route_gate:
    "The persistent alternatives begin here."
    menu:
        "Follow the long red route":
            jump red_route
        "Follow the blue route":
            jump blue_route

label red_route:
    scene red_one
    "The red route owns its first child scene."
    scene red_two
    "The red route owns its second child scene."
    call repeatable_stop
    jump early_ending

label blue_route:
    scene blue_one
    "The blue route remains a separate child scope."
    return

label repeatable_stop:
    scene repeatable_room
    "The repeatable stop is represented once."
    menu:
        "Repeat the stop":
            jump repeatable_stop
        "Finish the stop":
            return
