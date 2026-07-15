default gate_one = False
default gate_two = False
default gate_three = False

label start:
    call open_room
    $ gate_one = True
    if gate_one:
        call gated_one
    $ gate_two = True
    if gate_two:
        call gated_two
    $ gate_three = True
    if gate_three:
        call gated_three
    jump ending

label gated_one:
    scene one_room
    "The first gated occurrence."
    return

label open_room:
    scene open_room
    "The ordinary ungated occurrence."
    return

label gated_two:
    scene two_room
    "The second gated occurrence."
    return

label gated_three:
    scene three_room
    "The third gated occurrence."
    return

label ending:
    scene station
    "The route ends here."
    return
