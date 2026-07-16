default score = 0
default route = None

label start:
    scene foyer
    "The route begins in the foyer."
    menu:
        "Practice first":
            jump practice_hub
        "Take the short detour":
            "The detour is temporary."
    "The temporary detour rejoins the foyer route."
    jump shared_entry

label practice_hub:
    scene courtyard
    "Practice can be repeated before trying the gate."
    menu:
        "Practice once":
            $ score += 1
            jump practice_hub
        "Try the score gate" if score >= 3:
            jump score_target
        "Leave practice":
            jump shared_entry

label score_target:
    scene observatory
    "The score-gated scene has been reached."
    jump shared_entry

label shared_entry:
    call shared_memory
    menu:
        "Use the first route":
            jump first_route
        "Use the second route":
            jump second_route

label first_route:
    scene gallery
    "The first route reaches the shared memory from one caller."
    call shared_memory
    jump commitment_gate

label second_route:
    scene library
    "The second route reaches the shared memory from another caller."
    call shared_memory
    jump commitment_gate

label commitment_gate:
    "A persistent commitment is required."
    menu:
        "Commit to red":
            $ route = "red"
            jump red_route
        "Commit to blue":
            $ route = "blue"
            jump blue_route

label red_route:
    scene red_room
    "The red commitment stays separate."
    call shared_memory
    jump red_ending

label blue_route:
    scene blue_room
    "The blue commitment stays separate."
    call shared_memory
    jump blue_ending

label shared_memory:
    scene memory
    "This scene has several exact call-site occurrences."
    return

label ending:
    scene station
    "The ordinary route ends here."
    return

label red_ending:
    scene red_station
    "The red route ends here."
    return

label blue_ending:
    scene blue_station
    "The blue route ends here."
    return

label unresolved_transfer:
    "A dynamic transfer may reach a destination that static analysis cannot close."
    jump expression dynamic_destination

label statically_unreachable:
    scene sealed_room
    "No resolved static route enters this scene."
    return

label conflicting_target:
    if route == "red" and route == "blue":
        scene contradiction_room
        "This target has mutually conflicting supported requirements."
    return
