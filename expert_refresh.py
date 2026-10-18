"""One-shot beta refresh bridge; install no scheduler and make no paid AI calls."""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from expert_beta import clock, instant
from expert_beta_cli import import_package


def atomic(path, data):
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
        json.dump(data,stream);stream.flush();os.fsync(stream.fileno());name=stream.name
    os.replace(name,path)


def refresh(lab, store, runner=subprocess.run):
    lab, store = Path(lab).resolve(), Path(store).resolve()
    if not (lab/'scout_release.py').is_file():
        raise ValueError('Existing Scout release entrypoint required')
    store.mkdir(parents=True,exist_ok=True)
    with (store/'refresh.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        started=clock()
        try:
            runner([sys.executable,str(lab/'scout_release.py')],cwd=lab,check=True,timeout=600,
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pointer=json.loads((lab/'outputs/release_state/latest_release.json').read_text())
            if instant(pointer['completed_at_utc']) < started:
                raise ValueError('Collector did not produce a new successful release')
            package=Path(pointer['package']).resolve()
            if not package.is_relative_to(lab/'outputs/launch_candidates'):
                raise ValueError('Unexpected package destination')
            versions=import_package(store,package)
            result={'status':'imported','completed_at':clock().isoformat(),'package':str(package),'versions':versions,
                    'expert_generation':'pending approved provider and review; no paid calls made'}
            atomic(store/'last_refresh.json',result)
            return result
        except Exception as error:
            atomic(store/'last_refresh_failure.json',{'status':'failed; previous forecasts preserved','at':clock().isoformat(),'error_type':type(error).__name__})
            raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lab',required=True);parser.add_argument('--store',required=True)
    args=parser.parse_args();print(json.dumps(refresh(args.lab,args.store),indent=2))
