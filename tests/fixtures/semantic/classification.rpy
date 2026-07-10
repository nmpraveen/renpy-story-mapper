label start:
    "Begin."
    call utility
    jump chapter_two

label utility:
    $ persistent.visits += 1
    return

label chapter_two:
    "A new chapter."
    return

label unused_note:
    pause 1
    return
