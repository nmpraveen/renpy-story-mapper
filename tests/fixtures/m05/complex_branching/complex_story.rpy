# Synthetic fixture for deterministic Story Mapper validation.
# This file contains no assets, imports, Python blocks, or executable game helpers.

label start:
    "Rain silvered the harbor while the last ferry tied up for the night."
    "Ropes creaked at the moorings, marking each gust before it reached the quay."
    mira "The beacon failed three evenings ago. Since then, every boat arrives by luck."
    jonas "The council will listen at dawn, but only if we bring them a workable plan."
    "Above them, the lighthouse lantern room remained a perfect black circle."
    "A brass token rested in Mira's palm, stamped with the crest of the old lighthouse."
    mira "This token opens no door, but people remember what it represents."
    $ trust = 0
    $ courage = 0
    $ coins = 2
    $ route = "undecided"
    $ inventory_rope = False
    $ inventory_lens = False
    $ archive_key = False
    $ lens_polished = False
    $ council_support = 0
    $ market_rounds = 0
    $ chapter = 1
    $ storm_warning = False
    $ secret_chart = False
    $ harbor_saved = False
    "A buoy bell answered the clock from somewhere inside the fog."
    "Jonas unfolded a town map and weighted its corners with smooth gray stones."
    jonas "The western road floods first, so every useful path begins here at the quay."
    mira "And every path must bring us back before the packet boat reaches the reef."
    "They divided the night into three tasks: learn, prepare, and persuade."
    "The town clock struck nine, leaving only one night to prepare."
    jump harbor_arrival

label harbor_arrival:
    "Lanterns swayed above the quay as merchants packed away their stalls."
    "A sailmaker barred his windows while apprentices carried canvas above the tide line."
    "Across the square, the records office showed one narrow stripe of lamplight."
    mira "We can investigate the tower, search the archive, or earn more supplies first."
    jonas "Whatever we choose, the storm will not wait for us."
    "The ferry master called the final departure and pulled in the gangway."
    mira "Listen carefully. Every promise tonight costs time, trust, or coin."
    menu:
        "Ask Mira why she trusts the old beacon":
            mira "My mother kept it lit. I know what its light meant to people out there."
            $ trust += 1
            "Her answer made the task feel less like a puzzle and more like a promise."
            menu:
                "Promise to restore her family's light":
                    $ trust += 1
                    $ courage += 1
                    $ route = "lighthouse"
                    mira "Then we start with the tower."
                    jump lighthouse_route
                "Offer to research the failure before promising":
                    $ route = "archive"
                    $ archive_key = True
                    jonas "Cautious, but sensible. The records office is still open."
                    jump archive_route
        "Buy a coil of climbing rope" if coins >= 2:
            $ coins -= 2
            $ inventory_rope = True
            shopkeeper "Strong hemp, tested on the northern cliffs."
            menu:
                "Head directly to the lighthouse":
                    $ route = "lighthouse"
                    jump lighthouse_route
                "Visit the market again for more preparation":
                    jump market_rounds
        "Help the stranded fisher for a coin":
            fisher "Carry this crate and I can spare a little from today's catch."
            $ coins += 1
            $ trust += 1
            "Together they moved the crate beyond the reach of the rising tide."
            jump market_rounds
        "Enter the records office before it closes":
            $ route = "archive"
            jonas "The oldest maintenance ledgers should mention the beacon lens."
            jump archive_route

label market_rounds:
    "The night market formed a bright island between the dark sea and shuttered homes."
    "Fishmongers covered their tables, but tool sellers stayed for the repair crews."
    "A chalkboard listed the tide, the wind, and the minutes remaining before closure."
    shopkeeper "Choose what helps. I will not sell you weight you cannot carry."
    "Mira counted their coins while Jonas compared the market lanes on his map."
    $ market_rounds += 1
    if market_rounds < 2:
        "There was still enough time for one careful errand before the bells rang."
    else:
        $ storm_warning = True
        "A watch bell warned that the storm front had crossed the outer reef."
    menu:
        "Perform a brave harbor rescue" if courage > 0:
            "A loose skiff knocked against the pilings while its owner called from shore."
            $ courage += 1
            $ coins += 2
            $ trust += 1
            "The skiff was secured, and the grateful owner pressed two coins into Mira's hand."
            if market_rounds < 2:
                "One row of stalls remained open."
                jump market_rounds
            else:
                "With the market closing, the lighthouse path was the quickest route onward."
                $ route = "lighthouse"
                jump lighthouse_route
        "Trade the brass token for three coins":
            "Mira turned the token over twice before setting it on the trader's cloth."
            $ coins += 3
            $ trust -= 1
            trader "A collector will value it. I hope you will not miss it."
            menu:
                "Purchase a polished lens blank" if coins >= 3:
                    $ coins -= 3
                    $ inventory_lens = True
                    $ lens_polished = True
                    "The glass caught every nearby lantern and gathered them into one clear point."
                    $ route = "lighthouse"
                    jump lighthouse_route
                "Save the coins and search the archive":
                    $ route = "archive"
                    jump archive_route
        "Buy the archivist's spare key" if coins >= 3:
            $ coins -= 3
            $ archive_key = True
            archivist "Return it before sunrise, and keep ink away from the warded shelves."
            $ route = "archive"
            jump archive_route
        "Leave the market for the lighthouse":
            $ route = "lighthouse"
            jump lighthouse_route

label lighthouse_route:
    "The lighthouse stood above the harbor, its windows black against the clouds."
    "Sea grass bent flat along the cliff, pointing inland beneath the wind."
    "Each dark pane reflected the town's scattered lanterns but offered no light of its own."
    mira "The service door is swollen shut, and the cliff stairs have lost three rails."
    if inventory_rope and courage > 0:
        "They anchored the rope to an iron ring and crossed the broken section together."
        $ courage += 1
        $ trust += 1
    elif inventory_rope:
        "The rope made the crossing possible, though every gust tested their nerve."
        $ courage += 1
    else:
        "Without rope, they followed a longer path through the keeper's garden."
        $ storm_warning = True
    "Inside, salt coated the gears and a cracked lens leaned against the wall."
    "A keeper's coat still hung beside the door, stiff with years of salt."
    "The winding mechanism resisted at first, then moved with a low iron sigh."
    jonas "The foundation is sound. The failure is somewhere in the focusing assembly."
    "A narrow stair curled upward through the center of the tower."
    menu:
        "Polish and install the lens blank" if inventory_lens:
            $ lens_polished = True
            $ council_support += 1
            mira "This will focus the flame, if the old mirror still turns."
        "Repair the mirror by hand" if courage > 0:
            $ courage += 1
            $ council_support += 1
            "Jonas held the frame steady while Mira aligned its worn teeth."
        "Mark the damage and seek archival instructions":
            $ route = "archive"
            $ archive_key = True
            "They copied every maker's mark before descending to the records office."
            jump archive_route
    "A hidden panel clicked open behind the counterweight."
    "Mira brushed dust from a hand-painted compass rose inside the door."
    if trust >= 2 and courage > 0:
        $ secret_chart = True
        "Inside lay a tide chart covered with notes in Mira's mother's hand."
        mira "She found a safe channel that never appeared on public maps."
    else:
        "The panel was empty except for a circle of faded blue paint."
    $ chapter = 2
    call shared_council
    "After the council meeting, the tower team returned to the rain-soaked square."
    jump final_confrontation

label archive_route:
    "The records office smelled of wet wool, lamp oil, and old paper."
    "Cabinets climbed to the ceiling, each drawer marked by year and vessel class."
    "Rain tapped the high windows with the steady rhythm of a clerk's pen."
    archivist "Public ledgers are on the left. Restricted charts require a council key."
    "The archivist placed blotting paper beside them and returned to the front desk."
    if archive_key:
        "The spare key opened a narrow cabinet behind the main desk."
        $ council_support += 1
    else:
        "Without a key, they began with the public repair accounts."
    menu:
        "Study the keeper's maintenance ledger":
            "The final entry described a warped gear and an emergency focusing plate."
            $ courage += 1
            $ lens_polished = True
            jonas "We can reproduce the adjustment at the tower."
        "Read the sealed tide chart" if archive_key and trust >= 1:
            $ secret_chart = True
            $ trust += 1
            mira "These markings match the stories my mother told me."
            "The chart revealed a sheltered channel behind the eastern reef."
        "Interview the night archivist":
            archivist "The council ignored three repair requests because the harbor fund was low."
            $ council_support += 1
            $ trust += 1
    "A loose page beneath the ledger listed the names of volunteer keepers."
    "Several names appeared in different inks, evidence of decades of shared watches."
    "The newest line was blank, waiting beneath a date written twenty years earlier."
    if route == "archive" and archive_key:
        "The archivist added their names to the list and stamped the page."
        $ council_support += 1
    else:
        "They copied the list without altering the record."
    if secret_chart and courage > 0:
        "Mira traced the safe channel from the archive window to the dark water below."
    elif lens_polished:
        "Jonas packed the focusing instructions into a waxed envelope."
    else:
        "They left with testimony, but no direct repair method."
    $ chapter = 2
    call shared_council
    "When the council adjourned, the archive team followed the crowd into the square."
    jump final_confrontation

label shared_council:
    "The council chamber filled with captains, shopkeepers, and families from the quay."
    "Wet coats steamed near the stove while the storm rattled the tall windows."
    "A model ship occupied the center table, surrounded by ledgers and empty cups."
    councilor "You asked for the floor. Tell us why the town should follow your plan."
    "Mira set the brass token where every council member could see it."
    if trust >= 2:
        mira "The beacon is more than a tower. It is a promise we make to every crew."
        $ council_support += 1
    else:
        jonas "The repair records show a practical risk to every vessel entering after dark."
    if courage > 0:
        "The rescued fisher stood and vouched for their willingness to act."
        $ council_support += 1
    else:
        "The room remained polite, but uncertain."
    menu:
        "Ask the council to fund the repair" if council_support >= 2:
            $ coins += 3
            $ council_support += 1
            councilor "The emergency reserve is yours, with the harbor's thanks."
        "Offer the remaining coins to the harbor fund" if coins >= 3:
            $ coins -= 3
            $ council_support += 1
            mira "We will begin with what we have and account for every coin."
        "Request only volunteers":
            $ trust += 1
            councilor "Then everyone who joins does so by choice."
    "A thunderclap shook dust from the rafters."
    "The chamber doors opened, and a watch runner arrived breathing hard."
    runner "The wind shifted east. Whatever you decide must begin now."
    if storm_warning:
        councilor "The outer watch has lost sight of an incoming packet boat."
    else:
        councilor "The packet boat is due before dawn. We have one chance to guide it."
    return

label final_confrontation:
    "Everyone converged beneath the lighthouse as the storm swallowed the horizon."
    "Volunteers formed a chain from the supply cart to the tower door."
    "The councilor kept the square clear while Jonas checked each signal lantern."
    "The packet boat's bell sounded once beyond the reef, then vanished under the wind."
    mira "We choose now: light the beacon, signal the safe channel, or shelter the harbor."
    jonas "No plan is perfect, but one clear signal is better than five uncertain ones."
    "The packet boat's bell sounded again, closer to the reef than before."
    "Mira looked from the tower to the hidden channel and finally to the waiting town."
    if route == "lighthouse" and lens_polished:
        "The repaired lens waited in the tower, ready to gather the flame."
    elif route == "archive" and archive_key:
        "The copied instructions and stamped volunteer list gave the plan authority."
    else:
        "Their preparations were incomplete, but the harbor still watched for a decision."
    menu:
        "Light the restored beacon" if lens_polished and council_support >= 2:
            $ harbor_saved = True
            $ chapter = 3
            "The mirror turned, and a clean beam swept across the black water."
            jump ending_good
        "Guide the boat through the hidden channel" if secret_chart and trust >= 2 and courage > 0:
            $ harbor_saved = True
            $ chapter = 4
            "Mira climbed the signal mast and flashed the chart's secret sequence."
            jump ending_secret
        "Build a shore fire with the remaining supplies" if coins >= 3:
            $ coins -= 3
            $ chapter = 3
            "A broad orange fire marked the beach, safer than darkness but short of the harbor mouth."
            jump ending_neutral
        "Sound the evacuation bell":
            $ trust -= 1
            $ chapter = 3
            "The town moved uphill while the packet boat searched for the harbor alone."
            jump ending_bad
    "If no declared plan could be followed, the watch prepared a last uncertain signal."
    jump expression emergency_route

label ending_good:
    "The packet boat followed the beacon between the reefs and entered calm water at dawn."
    "Cheers moved along the quay faster than the first sunlight."
    "The restored beam faded against the morning, but nobody hurried to extinguish it."
    captain "That light gave us the harbor when the rain erased everything else."
    mira "Then we keep it burning, together."
    "The captain rang the ship's bell three times in salute."
    $ trust += 1
    $ harbor_saved = True
    "The council appointed a new volunteer watch, and the restored tower became its shared duty."
    "Jonas entered the repair method in the public ledger for whoever kept the next watch."
    "GOOD ENDING — The Harbor Light"
    return

label ending_bad:
    "From the hill, the town watched the packet boat turn away from the unmarked coast."
    "Its bell grew faint, then disappeared beyond the rain."
    "The evacuation kept the streets orderly, but the silent tower accused every window."
    jonas "No lives were lost here, but fear made the choice for us."
    $ council_support -= 1
    $ harbor_saved = False
    "By morning, the storm had broken the empty lighthouse windows."
    "Mira recovered the brass token from the mud and closed her hand around it."
    "BAD ENDING — The Dark Harbor"
    return

label ending_neutral:
    "The shore fire guided the packet boat to anchor outside the reef until sunrise."
    "Volunteers fed driftwood to the flames until the rain softened."
    "The beacon remained dark, yet the orange glow held steady on the beach."
    captain "We waited out the worst of it. The cargo is late, but everyone is safe."
    $ harbor_saved = True
    $ coins = 0
    "The council postponed the lighthouse repair and posted extra watches along the beach."
    "Mira accepted the delay, then wrote the first name on a new volunteer schedule."
    "NEUTRAL ENDING — A Patient Dawn"
    return

label ending_secret:
    "The packet boat turned at Mira's final flash and slipped behind the eastern reef."
    "Only those on the signal platform could see how close the channel ran to the cliffs."
    "Jonas recorded the timing of every flash without copying the channel itself."
    "There, the storm fell quiet inside a channel hidden from every ordinary chart."
    mira "My mother left this path for someone willing to earn the truth of it."
    "Mira folded the weathered chart along its original creases."
    $ trust += 2
    $ harbor_saved = True
    $ route = "keepers"
    "At sunrise, Mira sealed a copy of the chart and entrusted it to the new keepers."
    "The public ledger recorded a safe arrival and left the hidden route unnamed."
    "SECRET ENDING — The Keeper's Channel"
    return
