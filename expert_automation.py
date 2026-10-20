"""Lightweight Expert-only worker: import sealed production, draft, publish reviews.

No NFL result refresh, statistical collection, Scout prediction run or payment calls.
Never performs Gemini requests unless the two existing free-tier opt-ins are set.
No report approval is synthesized: only separately approved reviews can publish.
"""
import argparse
import json
import os
from pathlib import Path


def execute_once(source=None, root=None, archive=None, *, publish_reports=None):
    source = Path(source or Path(__file__).resolve().parent)
    root = Path(root or '/var/data/site-data')
    archive = Path(archive or os.environ.get('TREND_FINDAH_EXPERT_STORE', '/var/data/expert_beta'))
    if publish_reports is None:
        publish_reports = os.environ.get('TREND_FINDAH_EXPERT_AUTO_PUBLISH') == '1'

    from expert_beta import clock
    from plug_publication import publish
    status = {'checked_at': clock().isoformat(), 'state': 'ok'}
    try:
        # Idempotent, strictly provenance-checked; no forecasts computed.
        status['production_import'] = publish(root, archive, source/'automatic_model.json')
        # Missing env flag means zero Gemini calls, not a dummy provider.
        if os.environ.get('TREND_FINDAH_EXPERT_AUTO_DRAFT') == '1':
            from expert_auto_queue import bounded_run
            draft = bounded_run(archive,
                os.environ.get('TREND_FINDAH_EXPERT_GEMINI_MODEL','gemini-2.5-flash'),
                daily_limit=int(os.environ.get('TREND_FINDAH_EXPERT_DAILY_LIMIT','2')),
                run_limit=int(os.environ.get('TREND_FINDAH_EXPERT_RUN_LIMIT','1')),
                execute=True)
            status['drafts'] = draft
            if draft['state'] == 'operator_review_required':
                status['state'] = 'needs_review'
        else:
            status['drafts'] = 'disabled'
        if publish_reports:
            from expert_review_publication import run
            status['review_publication'] = run(archive, execute=True, auto_feature=True)
        else:
            status['review_publication'] = 'disabled'
    except Exception as error:
        status['state'] = 'failed'
        status['error_type'] = type(error).__name__
        # Don't leak provider keys, prompts, or private reports into logs.
        raise
    finally:
        target = root/'logs'/'expert_automation_status.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(status, indent=2))
        tmp.replace(target)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if not args.once:
        parser.error('Use --once (for the dedicated Render worker)')
    if os.environ.get('TREND_FINDAH_ENV') != 'production' or os.environ.get('TREND_FINDAH_AUTO_UPDATE') != '1':
        parser.error('Production Expert worker requires existing hosted environment')
    print(json.dumps(execute_once(), indent=2))


if __name__ == '__main__':
    main()
