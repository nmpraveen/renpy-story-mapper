label start:
    $ trust = 0
    menu:
        "Help" if ready:
            $ trust += 1
            call helper
        "Leave":
            jump ending
    "The temporary branch rejoins."
    jump loop_entry

label helper:
    if trust > 0:
        "Trust changed."
    return

label loop_entry:
    menu:
        "Again":
            jump loop_entry
        "Finish":
            jump ending

label ending:
    return

label unreachable:
    "Not reachable in the resolved static graph."
    return

label dynamic_dispatch:
    jump expression destination
