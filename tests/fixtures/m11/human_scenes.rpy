label start:
    "The story opens."
    $ chapter = 1
    menu:
        "Take a short look":
            "The short detour stays in this scene."
        "Continue":
            "The direct arm stays here."
    "The short choice rejoins."

    menu:
        "Visit town":
            scene park
            "The park is the first arm-local scene."
            scene cafe
            "The cafe is the second arm-local scene."
        "Stay home":
            scene bedroom
            "Home is a separate arm-local scene."
    "The multi-scene temporary choice rejoins later."

    call shared_memory
    if ready:
        call guarded_memory
    call technical_helper
    jump day_two

label day_two:
    $ chapter += 1
    scene street
    "The next chapter begins after the progression assignment."
    jump route_gate

label alternate_context:
    "A second story context begins."
    call shared_memory
    return

label route_gate:
    "The persistent route split begins."
    menu:
        "Red route":
            jump red_route
        "Blue route":
            jump blue_route

label red_route:
    scene red_room
    "The red route remains separate."
    call shared_memory
    return

label blue_route:
    scene blue_room
    "The blue route remains separate."
    call shared_memory
    return

label hub:
    scene town_square
    "The repeatable event hub is available."
    menu:
        "Visit the market":
            call market_event
            jump hub
        "Visit the docks":
            call docks_event
            jump hub
        "Leave the hub":
            return

label market_event:
    scene market
    "The market event can repeat."
    return

label docks_event:
    scene docks
    "The docks event can repeat."
    return

label shared_memory:
    scene memory
    "This narrative callee is shared by several story contexts."
    return

label guarded_memory:
    "This narrative callee is guarded at its call site."
    return

label technical_helper:
    $ audit_count += 1
    return
