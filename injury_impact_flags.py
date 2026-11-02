"""Explicit historical game tags for material in-game injury impacts.

These tags are research context only. They never alter official grades,
immutable selections, or published records.
"""

_INJURY_IMPACT_FLAGS = {
    "2026_08_BAL_BUF": {
        "title": "Baltimore lost both quarterbacks during the game",
        "details": (
            "Lamar Jackson injured his right thumb on Baltimore's first "
            "offensive snap and did not return. Backup Tyler Huntley later "
            "left with a toe injury, sending undrafted rookie Joe Fagnano "
            "into his NFL debut. Baltimore finished with 10 points in the "
            "36–10 loss."
        ),
        "analysis_tag": "injury_distorted",
    },
}


def for_game(game_id):
    """Return a copy of the injury-context tag for this exact game, if any."""
    flag = _INJURY_IMPACT_FLAGS.get(game_id)
    return dict(flag) if flag else None
