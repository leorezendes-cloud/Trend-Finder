"""Opt-in, research-only finalization of dynamic pregame revisions.

Final receipts are kept separate from legacy official selections. Running this
after kickoff never uses a fresh market price or re-runs a model.
"""
from datetime import datetime, timezone
from pathlib import Path
from plug_dynamic_closing import finalize
from plug_dynamic_journal import _time


def finalize_due(root, *, as_of_utc=None):
    root=Path(root)
    at=_time(as_of_utc or datetime.now(timezone.utc).isoformat())
    journal_dir=root/"plug_dynamic_research"
    results={"due":0,"locked":0,"missing":0,"errors":0,"issues":{}}
    if not journal_dir.is_dir():
        return results
    from plug_dynamic_journal import read
    for path in sorted(journal_dir.glob("*.jsonl")):
        game_id=path.stem
        try:
            history=read(root,game_id)
            if not history or at<_time(history[-1]["kickoff_utc"]):
                continue
            results["due"]+=1
            receipt=finalize(root,game_id,as_of_utc=at.isoformat())
            results["locked"]+=int(receipt is not None)
            results["missing"]+=int(receipt is None)
        except (ValueError,KeyError,OSError,TypeError) as error:
            results["errors"]+=1
            results["issues"][game_id]=type(error).__name__+": "+str(error)
    return results
