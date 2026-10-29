"""Byte-preserving sharing for immutable captured evidence. No compression format.

Every logical filename remains a regular readable file. Only byte-identical
archives may share an inode. Active CSVs, receipts and journals are never pooled.
"""
import hashlib
import os
import stat
import tempfile
from pathlib import Path

CHUNK = 256 * 1024


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def identical(left, right):
    with Path(left).open('rb') as a, Path(right).open('rb') as b:
        while True:
            first, second = a.read(CHUNK), b.read(CHUNK)
            if first != second:
                return False
            if not first:
                return True


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def share_file(canonical, destination):
    """Atomically share verified immutable bytes; return released disk blocks.

    Caller holds the appropriate archive/update locks. No fallback deletes or
    truncates a destination if linking fails (e.g. another filesystem).
    """
    canonical, destination = Path(canonical), Path(destination)
    a, b = canonical.lstat(), destination.lstat()
    if not stat.S_ISREG(a.st_mode) or not stat.S_ISREG(b.st_mode):
        raise ValueError('Only regular archive files may share storage')
    if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino):
        return 0
    if (a.st_dev, a.st_size, stat.S_IMODE(a.st_mode), a.st_uid, a.st_gid) != (
            b.st_dev, b.st_size, stat.S_IMODE(b.st_mode), b.st_uid, b.st_gid):
        raise ValueError('Archive metadata differs')
    if not identical(canonical, destination):
        raise ValueError('Archive bytes differ')
    descriptor, name = tempfile.mkstemp(prefix='.share-', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.unlink()
        os.link(canonical, temporary, follow_symlinks=False)
        if (not identical(temporary, destination)
                or _identity(canonical.lstat()) != _identity(a)
                or _identity(destination.lstat()) != _identity(b)):
            raise ValueError('Archive changed during sharing')
        # Fully written bytes are durable before exchanging directory entries.
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        sync_directory(destination.parent)
        return b.st_blocks * 512 if b.st_nlink == 1 else 0
    finally:
        temporary.unlink(missing_ok=True)


def _matches_raw(path, raw):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != len(raw):
        return False
    offset = 0
    with path.open('rb') as stream:
        while block := stream.read(CHUNK):
            if block != raw[offset:offset+len(block)]:
                return False
            offset += len(block)
    return offset == len(raw)


def _store_unique(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.capture-',delete=False) as stream:
        pending=Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
    try:
        try:
            os.link(pending,path,follow_symlinks=False)
            sync_directory(path.parent)
        except FileExistsError:
            if not _matches_raw(path,raw):
                raise ValueError('Immutable evidence object conflict')
    finally:
        pending.unlink(missing_ok=True)


def save_capture(path, raw):
    """Save each observation under its original name, sharing repeated payloads.

    Acquisition timestamps and manifest hashes remain independent of physical
    storage; identical HTML does not invent another observation timestamp.
    """
    path = Path(path)
    if path.suffix not in ('.html', '.json') or path.name.endswith('-manifest.json'):
        raise ValueError('Expected a raw capture filename')
    pool = path.parent / '_objects'
    if pool.is_symlink():
        raise ValueError('Symlink in raw evidence pool')
    digest = hashlib.sha256(raw).hexdigest()
    object_path = pool/(digest+path.suffix)
    # Validate the final name before creating any new object on a conflicting retry.
    if path.exists() or path.is_symlink():
        if not _matches_raw(path,raw):
            raise ValueError('Captured evidence filename conflict')
        return digest
    if object_path.is_symlink():
        raise ValueError('Symlink in raw evidence pool')
    if object_path.exists():
        if not _matches_raw(object_path,raw):
            raise ValueError('Immutable evidence object conflict')
    else:
        _store_unique(object_path,raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(object_path, path, follow_symlinks=False)
    except FileExistsError:
        if not _matches_raw(path,raw):
            raise ValueError('Captured evidence filename conflict')
    sync_directory(path.parent)
    return digest
