"""Dugout's own reader (and careful writer) for PES 2021 / FL26 Master League saves.

crypto     the save file's encryption: decrypt, and encrypt back (with the SHA-512 checks the game uses)
container  the zlib-compressed block inside the save that holds the career player table
career     the career player table, clocks, squads, player states, Game Plans
world      clubs, fixtures with line-ups, league tables and rankings, knockout ties
club       the managed club's screen data (squad details, youth team, deals, club stats)
"""
