label start:
    call helper
    "After static call."
    call expression dynamic_destination
    "After dynamic call."
    call missing_helper
    "After missing call."
    call external_helper
    "After out-of-scope call."
    return

label helper:
    return
