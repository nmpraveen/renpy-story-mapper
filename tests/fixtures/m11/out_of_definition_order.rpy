label start:
    scene opening
    "Start."
    jump later

label ending:
    scene ending_room
    "Ending."
    return

label later:
    scene later_room
    "Later."
    jump ending
