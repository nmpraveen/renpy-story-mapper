label start:
    call helper
    "First continuation."
    call helper
    "Second continuation."
    return

label helper:
    menu:
        "Return A":
            return
        "Return B":
            return

label loop_entry:
    menu:
        "Again":
            jump loop_entry
        "Leave":
            return

label recursive:
    call recursive
    return

label never_returns:
    jump never_returns

label calls_never_returns:
    call never_returns
    "Unreachable continuation."
    return

label dynamic_arm:
    menu:
        "Known":
            return
        "Dynamic":
            jump expression destination
