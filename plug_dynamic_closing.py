"""Immutable dynamic closing receipt derived exclusively from saved pre-kickoff revisions.

Separate from legacy official selections until publication migration is validated.
No market lookup, model rerun or post-kickoff revision is possible here.
"""
import hashlib
import json
from pathlib import Path

from plug_dynamic_journal import read, _time
from plug_publication import immutable


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _destination(root, game_id):
    if not game_id or not all(c.isalnum() or c in "_-" for c in game_id):
        raise ValueError("Invalid game ID")
    return Path(root) / "plug_dynamic_closing" / (game_id + ".json")


def read_closing(root, game_id):
    path = _destination(root, game_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_bytes())
    checksum = payload.pop("receipt_sha256", None)
    if not checksum or hashlib.sha256(_canonical(payload)).hexdigest() != checksum:
        raise ValueError("Dynamic closing receipt checksum mismatch")
    if payload.get("game_id") != game_id or payload.get("kind") != "dynamic-closing-v1":
        raise ValueError("Invalid dynamic closing identity")
    history = read(root, game_id)
    if not history or history[-1]["sha256"] != payload["revision_sha256"]:
        raise ValueError("Closing revision no longer matches journal")
    if (payload["revision"] != history[-1]["revision"]
            or _time(payload["kickoff_utc"]) != _time(history[-1]["kickoff_utc"])):
        raise ValueError("Closing revision identity mismatch")
    payload["receipt_sha256"] = checksum
    return payload


def finalize(root, game_id, *, as_of_utc):
    """Lock the last observed revision at/after kickoff; never fabricate one."""
    history = read(root, game_id)
    if not history:
        return None
    last = history[-1]
    if _time(as_of_utc) < _time(last["kickoff_utc"]):
        raise ValueError("Cannot finalize before kickoff")
    if _time(last["evaluated_utc"]) >= _time(last["kickoff_utc"]):
        raise ValueError("Post-kickoff revision cannot become a pick")
    payload = {"kind": "dynamic-closing-v1", "game_id": game_id,
               "kickoff_utc": last["kickoff_utc"], "revision": last["revision"],
               "revision_sha256": last["sha256"],
               "ats_selected": last["ats_selected"], "ats_side": last["ats_side"],
               "ats_away_line": last["ats_away_line"],
               "ou_selected": last["ou_selected"], "ou_side": last["ou_side"],
               "ou_market_total": last["ou_market_total"]}
    payload["receipt_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    path = _destination(root, game_id)
    # Do not create a contradictory receipt if a concurrent caller finalized
    # another revision; immutable() enforces the single-writer outcome.
    immutable(path, _canonical(payload))
    existing = read_closing(root, game_id)
    if existing != payload:
        raise ValueError("Conflicting immutable closing receipt")
    return existing
