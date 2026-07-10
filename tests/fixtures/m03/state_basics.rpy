label start:
    "Track explicit state changes."
    $ love += 1
    $ lust_points -= 2
    $ dating = True
    $ cheating = False
    $ wits = 3
    $ money -= 10
    $ job = "Company Z"
    $ chapter = 3
    call xp_up("lust")
    call set_relationship("alex", "dating", True)
    return
