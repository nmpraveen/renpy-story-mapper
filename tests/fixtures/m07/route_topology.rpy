label start:
    "Day 1 begins on the chronological spine."
    $ chapter = 1
    menu:
        "Take the garden path" if wits >= 2:
            $ love += 1
            "A short garden detour."
        "Stay on the avenue":
            "The direct path stays on the spine."
    "Both Day 1 paths reconverge here."
    call shared_memory
    "The shared memory returns to its caller."
    jump day_two

label day_two:
    "Day 2 begins after the proven merge."
    menu:
        "Investigate the market":
            "The outer detour opens."
            menu:
                "Ask the vendor" if money >= 10:
                    $ money -= 10
                    "The vendor shares a clue."
                "Watch quietly":
                    "A quiet clue appears."
            "The nested local detour closes."
        "Continue to the station":
            "The outer path stays direct."
    "All Day 2 detours reconverge at the station."
    jump route_gate

label route_gate:
    "The story reaches its persistent route fork."
    menu:
        "Commit to the red route" if red_points >= 3:
            $ route = "red"
            $ dating = True
            jump red_route
        "Commit to the blue route" if blue_points >= 3:
            $ route = "blue"
            $ job = "Harbor"
            jump blue_route
        "Refuse both routes":
            jump dead_end

label red_route:
    "The red route remains in its own lane."
    call shared_memory
    if courage >= 5:
        $ ending_unlocked = True
        jump game_ending
    else:
        jump route_ending

label blue_route:
    "The blue route remains in its own lane."
    jump update_boundary

label loop_entry:
    "A route-local patrol loop begins."
    menu:
        "Repeat patrol":
            jump patrol_loop
        "Stop at the current release":
            jump update_boundary

label patrol_loop:
    "The patrol loop returns to the same route choice."
    jump loop_entry

label shared_memory:
    "This shared scene is called from two distinct sites."
    $ insight += 1
    return

label game_ending:
    "The complete story reaches a game ending."
    return

label route_ending:
    "The red lane reaches a route ending."
    return

label dead_end:
    "This refusal is a dead end."
    return

label update_boundary:
    "This route stops at an update boundary."
    return

label unresolved_route:
    "A dynamic destination must remain unresolved."
    jump expression selected_destination

label technical_corridor:
    $ audit_step = 1
    $ audit_step += 1
    $ audit_step += 1
    $ audit_step += 1
    $ audit_step += 1
    "A technical one-in/one-out chain collapses into one corridor."
    return
