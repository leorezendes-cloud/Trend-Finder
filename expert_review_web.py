"""Owner-only pregame Expert review and immutable publication.

No AI calls, no scheduled work, no alteration to Scout seals or draft files.
The existing validate_expert and Store.append safeguards remain authoritative.
"""
import copy
import fcntl
import json
import re
import secrets
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from expert_beta import Store, clock, identity, instant, validate_expert

bp = Blueprint("expert_review", __name__, url_prefix="/owner/expert")
VERSION = re.compile(r"[0-9a-f]{64}\Z")


@bp.before_request
def owner_only():
    if not getattr(g, "is_owner", False):
        abort(403)
    if not current_app.config.get("EXPERT_BETA_ENABLED", False):
        abort(404)
    if request.method == "POST":
        expected = session.get("_csrf", "")
        received = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, received):
            abort(400, description="Review form expired. Reload the page.")


def _store():
    return Store(current_app.config["EXPERT_BETA_STORE"])


def _latest_draft(folder, version):
    """Prefer an explicit operator replacement over a previous original draft."""
    choices = []
    original = folder / (version + ".json")
    if original.is_file():
        choices.append((0, original))
    for path in folder.glob(version + ".replacement-*.json"):
        suffix = path.name[len(version + ".replacement-"):-len(".json")]
        if suffix.isdigit():
            choices.append((int(suffix), path))
    return max(choices, key=lambda x: x[0])[1] if choices else None


def pending_reports(store, *, now=None):
    now = now or clock()
    records = store.records()
    published = {identity(row["scout"]) for row in records if row.get("expert") is not None}
    imported = {}
    for row in records:
        if row.get("kind") != "production_import":
            continue
        scout = row["scout"]
        if instant(scout["game"]["kickoff_utc"]) <= now:
            continue
        game_id = identity(scout)
        if game_id in published:
            continue
        previous = imported.get(game_id)
        if previous is None or (row["generated_at"], row["version"]) > (previous["generated_at"], previous["version"]):
            imported[game_id] = row
    drafts = store.root / "drafts"
    pending = []
    for game_id, record in imported.items():
        path = _latest_draft(drafts, record["version"])
        if path is None:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Expert draft requires operator review: " + path.name) from exc
        if report.get("review_status") == "rejected":
            continue
        # Do not list an already rejected editorial review as new work.
        review = path.with_name(path.stem + ".review.json")
        if review.is_file():
            reviewed = json.loads(review.read_text(encoding="utf-8"))
            if reviewed.get("review_status") == "rejected":
                continue
        pending.append(dict(key=game_id, version=record["version"], game=record["scout"]["game"],
                            scout=record["scout"], report=report, path=path, review=review))
    return sorted(pending, key=lambda item: (instant(item["game"]["kickoff_utc"]), item["key"]))


def _find_pending(version, store):
    if not VERSION.fullmatch(version):
        abort(404)
    match = next((row for row in pending_reports(store) if row["version"] == version), None)
    if match is None:
        abort(404, description="Draft is no longer pending or kickoff has passed.")
    return match


def _ensure_public_featured(store, season, week):
    """Freeze two approved, upcoming free featured games if none are configured."""
    path = store.root / "featured" / f"{season}-{week}.json"
    if path.exists():
        return False
    upcoming = {}
    now = clock()
    for row in store.records():
        scout = row["scout"]
        game = scout["game"]
        if (row.get("expert") is None or int(game["season"]) != season or
                int(game["week"]) != week or instant(game["kickoff_utc"]) <= now):
            continue
        upcoming.setdefault(identity(scout), instant(game["kickoff_utc"]))
    if len(upcoming) < 2:
        return False
    chosen = [game_id.rsplit("/", 1)[1] for game_id, _ in
              sorted(upcoming.items(), key=lambda item: (item[1], item[0]))[:2]]
    from expert_beta_cli import feature
    feature(store.root, season, week, chosen)
    return True


@bp.get("/")
def queue():
    try:
        items = pending_reports(_store())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        current_app.logger.warning("Expert review queue unavailable: %s", type(exc).__name__)
        abort(503, description="The Expert review archive needs operator attention.")
    return render_template("expert_review_queue.html", items=items)


@bp.get("/<version>")
def detail(version):
    item = _find_pending(version, _store())
    return render_template("expert_review_detail.html", item=item)


@bp.post("/<version>/approve")
def approve(version):
    if request.form.get("confirm_review") != "yes":
        abort(400, description="Full report review must be confirmed.")
    store = _store()
    store.root.mkdir(parents=True, exist_ok=True)
    # Protect the publication decision against double-clicks / concurrent owners.
    with (store.root / "expert_review.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        item = _find_pending(version, store)
        report = copy.deepcopy(item["report"])
        report["review_status"] = "approved"
        report["reviewer"] = "site-owner-" + str(g.member["id"])
        report["reviewed_at"] = clock().isoformat()
        validate_expert(report, item["scout"])
        # Store.append is content-addressed and immutable. No draft is overwritten.
        store.append(item["scout"], expert=report, kind="development")
        g.pop("_expert_records", None)
        g.pop("_expert_featured", None)
        game = item["game"]
        try:
            _ensure_public_featured(store, int(game["season"]), int(game["week"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            current_app.logger.warning("Featured Expert selection unavailable: %s", type(exc).__name__)
        g.pop("_expert_records", None)
        g.pop("_expert_featured", None)
    # Only the featured text of an unchanged, unapproved newsletter may refresh.
    from newsletter import refresh_unapproved_featured
    try:
        status = refresh_unapproved_featured()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        current_app.logger.warning("Newsletter auto-refresh unavailable after Expert approval: %s", type(exc).__name__)
        status = "newsletter-refresh-unavailable"
    flash("Expert approved and published. Newsletter: " + status.replace("-", " ") + ".")
    return redirect(url_for("expert_review.queue"))


def init_app(app):
    app.register_blueprint(bp)
