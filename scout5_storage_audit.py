"""Read-only inventory for Scout 5.0 migration on a storage-constrained Render host.

Reports *existing* disk usage only. Never changes, copies or deletes files.
Use inside the running service container so ephemeral paths and persistent
/var/data volumes can be distinguished before choosing a Mac-only archive.
"""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path


def size(path):
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return None
    return 0


def journal_kind(folder):
    path=folder/"revisions.json"
    if not path.is_file():
        return "no-journal"
    try:
        obj=json.loads(path.read_text())
        rows=obj.get("rows") or []
        tags={r.get("totals",{}).get("model","legacy") for r in rows}
        return "scout5" if tags=={"scout5-ou-v1"} else "mixed" if "scout5-ou-v1" in tags else "legacy"
    except (OSError,ValueError,TypeError,AttributeError):
        return "unreadable"


def scout_summary(path):
    if not path.is_dir():
        return None
    dirs=[p for p in path.iterdir() if p.is_dir() and len(p.name.split("_"))==4]
    counts=Counter(journal_kind(p) for p in dirs)
    return {"path":str(path),"bytes":size(path),"game_directories":len(dirs),
            "journal_types":dict(counts),
            "game_bytes_by_type":{kind:sum(size(p) or 0 for p in dirs if journal_kind(p)==kind)
                                  for kind in counts}}


def inventory(root):
    root=Path(root).resolve()
    candidates=[root,Path("/var/data"),Path("/var/data/site-data"),
                Path("/var/data/expert_beta")]
    unique={}
    for item in candidates:
        if not item.exists():continue
        real=item.resolve()
        if real in unique:continue
        unique[real]=item
    payload={"service_root":str(root),"persistent_root":"/var/data",
             "read_only":True,"roots":[],"scout_journals":[]}
    for real,display in unique.items():
        try:
            usage=shutil.disk_usage(real)
            payload["roots"].append({"path":str(display),"resolved":str(real),
                "free_bytes":usage.free,"used_bytes":usage.used,"total_bytes":usage.total})
        except OSError:pass
    for candidate in (root/"scout_dynamic",Path("/var/data/site-data/scout_dynamic"),
                      Path("/var/data/scout_dynamic")):
        if not candidate.exists():continue
        real=candidate.resolve()
        if any(x.get("resolved")==str(real) for x in payload["scout_journals"]):continue
        found=scout_summary(candidate)
        if found:
            found["resolved"]=str(real)
            payload["scout_journals"].append(found)
    for sub in ("data/scout4/blend/predictions","data/scout4/shadow",
                "data/scout4/blend/inputs"):
        candidate=root/sub
        if candidate.exists():
            payload.setdefault("shared_seals",[]).append(
                {"path":str(candidate),"bytes":size(candidate)})
    for sub in ("production_sources","publication_events","drafts"):
        candidate=Path("/var/data/expert_beta")/sub
        if candidate.exists():
            payload.setdefault("protected_expert_store",[]).append(
                {"path":str(candidate),"bytes":size(candidate)})
    return payload


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",default=str(Path(__file__).resolve().parent))
    args=parser.parse_args()
    print(json.dumps(inventory(args.root),indent=2,sort_keys=True))
