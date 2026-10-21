"""Short-lived feed stage; launched only by the locked hosted updater.

No model code, forecasts, or publication is invoked here.
"""
import sys
from pathlib import Path


def arm_feed_deadline(seconds=180):
    """A hard deadline survives supervisor death, including blocked I/O/imports."""
    import signal
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.alarm(seconds)


def run(kind, root, season):
    # A single-use worker never needs to retain raw DataFrames in nflreadpy's
    # global cache. All persisted Scout CSVs/manifests remain unchanged.
    from nflreadpy.config import update_config, CacheMode
    update_config(cache_mode=CacheMode.OFF)
    if kind == 'finals':
        import update_nfl_games as finals
        finals.BACKUPS = root/'backups'
        result = finals.main(['--apply', '--season', str(season),
                              '--file', str(root/'nfl_games.csv')])
        if result not in (None, 0):
            raise RuntimeError('Finals refresh failed')
    elif kind == 'stats':
        from scout4.collect import collect
        collect(season, root/'data/scout4')
    else:
        raise ValueError('Unknown feed stage')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('finals', 'stats'))
    parser.add_argument('root', type=Path)
    parser.add_argument('season', type=int)
    args = parser.parse_args()
    arm_feed_deadline()
    import resource
    from hosted_updates import scheduler_event
    job = 'feed-'+args.kind
    scheduler_event(args.root, job, 'attempt')
    try:
        run(args.kind, args.root, args.season)
    except BaseException as error:
        scheduler_event(args.root, job, 'failure', error_type=type(error).__name__)
        raise
    else:
        scheduler_event(args.root, job, 'success')
    finally:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1048576 if sys.platform == 'darwin' else 1024
        scheduler_event(args.root, job, 'memory', peak_rss_mib=round(peak/divisor, 2))
