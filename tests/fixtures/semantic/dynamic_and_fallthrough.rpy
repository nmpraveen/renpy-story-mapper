label start:
    "Before the handoff."

label continued:
    "After the handoff."
    jump expression destination

label unreachable_story:
    "Nobody reaches this."
    return
