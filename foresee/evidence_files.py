"""POSIX file custody for experimental evidence commands.

Parent directories must be trusted. Private keys are unencrypted owner-only files.
"""
import os
from pathlib import Path
import stat
import tempfile

from .evidence_auth import _backend
from .evidence_format import _b64, _encode, _json, _unb64, key_id


def read_bounded(path, maximum, *, private=False):
    if os.name != 'posix':
        raise ValueError('evidence file custody requires POSIX')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('input must be a bounded regular file')
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError('private key must be owner-only, owned by this user, and not hard-linked')
        raw = source.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('input exceeds byte limit')
        return raw


def write_new(path, raw):
    """Publish a complete owner-only file atomically; never replace a destination."""
    if os.name != 'posix':
        raise ValueError('evidence file custody requires POSIX')
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.foresee-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def public_metadata(key):
    public = key.public_key().public_bytes_raw()
    return {'algorithm': 'Ed25519', 'keyid': key_id(public), 'public_key': _b64(public)}


def generate_key(path):
    private_type, _, _ = _backend()
    key = private_type.generate()
    raw = _encode({'version': 1, 'algorithm': 'Ed25519', 'seed': _b64(key.private_bytes_raw())})
    write_new(path, raw)
    return public_metadata(key)


def load_key(path):
    raw = read_bounded(path, 4096, private=True)
    try:
        value = _json(raw, 4096)
        if (type(value) is not dict or set(value) != {'version', 'algorithm', 'seed'}
                or type(value['version']) is not int or value['version'] != 1
                or value['algorithm'] != 'Ed25519'):
            raise ValueError('invalid key')
        seed = _unb64(value['seed'], 32)
        if len(seed) != 32:
            raise ValueError('invalid key')
    except ValueError:
        raise ValueError('invalid private key file') from None
    private_type, _, _ = _backend()
    return private_type.from_private_bytes(seed)
