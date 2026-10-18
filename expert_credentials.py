"""Private local Gemini credential storage; never print credential contents."""
import getpass
import json
import os
import stat
from pathlib import Path

CREDENTIAL_PATH = Path(__file__).resolve().parent/'instance/gemini_credentials.json'


def load_local():
    try:
        descriptor = os.open(CREDENTIAL_PATH, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise RuntimeError('Gemini credential file must be owned by you and readable only by you')
        value = json.load(stream)
    if not isinstance(value.get('api_key'), str) or not value['api_key'].strip():
        raise ValueError('Local Gemini key is missing')
    return value


def setup():
    import sys
    if not sys.stdin.isatty():
        raise SystemExit('Run this setup directly in your Mac Terminal for hidden key entry.')
    if CREDENTIAL_PATH.exists():
        raise SystemExit('A local key is already saved; no changes made.')
    key = getpass.getpass('Paste your Gemini API key (hidden), then press Return: ').strip()
    if not key or any(c.isspace() for c in key):
        raise SystemExit('Invalid empty or whitespace-containing key; nothing saved.')
    CREDENTIAL_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(CREDENTIAL_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump({'api_key': key, 'free_tier_confirmed': True,
                   'confirmation_basis': 'User confirmed Free Tier and disabled billing in project chat'}, stream)
        stream.flush();os.fsync(stream.fileno())
    print('Gemini key saved privately. No API request was made. Return to the chat and say ready.')


if __name__ == '__main__':
    setup()
