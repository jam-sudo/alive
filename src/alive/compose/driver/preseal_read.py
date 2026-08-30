"""Digest-bound reads of pre-seal artifacts, in ONE place.

``load_resolved_run_spec`` hashes each pre-seal pathname during validation. Every
consumer that then REOPENS the same pathname performs a second, separate read, so
"the declared digest was verified" says nothing about the bytes that were parsed.
An external audit reproduced a swap inside that window on 2026-08-24 and this
repository reproduced it independently.

The 2026-08-25 fix (`f73b63e`) closed that for the artifacts one loader parses --
and **missed its siblings**. The 2026-08-30 re-raise named them exactly: one JSON
lane inside the very file that was fixed (`phase2a_inputs`), plus the config load
in three independent subcommands and two raw byte reads in preflight. That is this
repository's dominant defect shape: a lesson applied at one site and not carried to
the others.

So the helper does not live in one consumer any more. It lives here, and every lane
calls it. Fixing this in one place is now the only way to fix it at all.

The error type is deliberately module-local: each caller converts it to whatever
its own contract already raises. Widening a caller's exception type to import this
one would redefine an existing contract in order to add a check, which this
repository has recorded as its own mistake before.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_HASH_CHUNK = 1 << 20

__all__ = [
    "PresealBytesError",
    "PresealDescriptorError",
    "read_verified_bytes",
    "read_verified_json",
    "verified_descriptor",
]


class PresealBytesError(ValueError):
    """The bytes read for consumption do not hash to the declared digest."""


class PresealDescriptorError(ValueError):
    """A descriptor-pinned read could not be established, or its bytes changed."""


def read_verified_bytes(path: str | Path, expected_sha256: str, *, field: str) -> bytes:
    """Read a pre-seal file ONCE and hash the bytes that were actually read.

    Parameters
    ----------
    path : str or pathlib.Path
        The pathname the validated run spec recorded.
    expected_sha256 : str
        The digest the validated run spec recorded for it.
    field : str
        Pre-seal field name, used only in the error message.

    Returns
    -------
    bytes
        The exact bytes whose digest matched the declared one.

    Raises
    ------
    PresealBytesError
        If the bytes read now do not hash to ``expected_sha256``.
    """
    data = Path(path).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise PresealBytesError(
            f"pre-seal {field}: bytes read for consumption hash to {actual}, not the "
            f"declared {expected_sha256} -- the file changed after the run spec verified it"
        )
    return data


def read_verified_json(path: str | Path, expected_sha256: str, *, field: str) -> dict[str, Any]:
    """Digest-bound JSON read: parse the same bytes that were hashed.

    Raises
    ------
    PresealBytesError
        If the digest does not match, or the payload is not a JSON object.
    """
    obj = json.loads(read_verified_bytes(path, expected_sha256, field=field))
    if not isinstance(obj, dict):
        raise PresealBytesError(f"pre-seal {field}: {path} is not a JSON object")
    return obj


@contextlib.contextmanager
def verified_descriptor(source_path: str | Path, expected_sha: str) -> Iterator[Path]:
    """Yield an fd-backed path to the integrity-checked sealed source.

    Opens the source with ``O_NOFOLLOW`` (rejecting a symlink final component),
    fstat-verifies it is a regular file, captures its
    ``(device, inode, size, mtime_ns)`` identity, streams the SHA-256, then
    re-captures the identity and requires it unchanged (a mutation during
    hashing fails closed). The streamed digest must equal ``expected_sha``.
    The original descriptor remains open while the yielded ``/proc/self/fd`` or
    ``/dev/fd`` path is used, closing the hash-then-reopen pathname race.

    Raises
    ------
    PresealDescriptorError
        On a symlink / non-regular node, an identity change during hashing, an
        unreadable file, a digest mismatch, or an unavailable/mismatched
        descriptor-backed path.
    """
    # The signature widened to `str | Path` when this moved here; the body below
    # uses Path methods, so coerce once rather than trusting every caller to pass
    # a Path. The bias lane passes `spec.pre_seal[...].path`, which is a str -- it
    # crashed with AttributeError instead of verifying, and a behavioural test
    # caught it. A widened parameter type that the body does not honour is not a
    # widened type.
    source_path = Path(source_path)
    if source_path.is_symlink():
        raise PresealDescriptorError(
            f"sealed source {str(source_path)!r} is a symlink (node-kind policy)"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(source_path, flags)
    except OSError as exc:
        raise PresealDescriptorError(
            f"cannot open sealed source {str(source_path)!r} (O_NOFOLLOW): {exc}"
        ) from exc
    try:
        pre = os.fstat(fd)
        if not stat.S_ISREG(pre.st_mode):
            raise PresealDescriptorError(
                f"sealed source {str(source_path)!r} is not a regular file (node-kind policy)"
            )
        identity_before = (pre.st_dev, pre.st_ino, pre.st_size, pre.st_mtime_ns)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, _HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
        post = os.fstat(fd)
        identity_after = (post.st_dev, post.st_ino, post.st_size, post.st_mtime_ns)
        if identity_before != identity_after:
            raise PresealDescriptorError(
                f"sealed source {str(source_path)!r} changed identity during hashing "
                f"(before={identity_before!r} after={identity_after!r})"
            )
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            raise PresealDescriptorError(
                f"sealed source {str(source_path)!r} digest mismatch "
                f"(expected {expected_sha!r}, got {actual_sha!r})"
            )

        os.lseek(fd, 0, os.SEEK_SET)
        descriptor_path: Path | None = None
        for candidate in (Path(f"/proc/self/fd/{fd}"), Path(f"/dev/fd/{fd}")):
            try:
                candidate_fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            except OSError:
                continue
            try:
                candidate_stat = os.fstat(candidate_fd)
                candidate_identity = (
                    candidate_stat.st_dev,
                    candidate_stat.st_ino,
                    candidate_stat.st_size,
                    candidate_stat.st_mtime_ns,
                )
            finally:
                os.close(candidate_fd)
            if candidate_identity == identity_after:
                descriptor_path = candidate
                break
        if descriptor_path is None:
            raise PresealDescriptorError(
                "cannot obtain an identity-matched descriptor path for sealed source "
                f"{str(source_path)!r}; refusing a pathname reopen"
            )
        yield descriptor_path

        # --- post-hash window: prove the bytes did not change under us ---------
        # 2026-08-30, `seal.verified-fd-posthash-mutation`, reproduced independently
        # on both sides of the audit loop: descriptor pinning defeats a *pathname*
        # swap, but not an IN-PLACE write to the inode we hold open. Measured on the
        # real function: `same_inode=True`, verified digest != the digest of the
        # bytes actually read through the descriptor.
        #
        # Prevention is not available at this layer -- a local writer with write
        # permission can modify a file we hold read-only, and nothing here can stop
        # it. What IS available is making the divergence impossible to go unnoticed,
        # which is the property the seal's evidence actually rests on: "the bytes we
        # recorded as verified are the bytes we consumed" must be true or the run
        # must fail. So the digest is re-streamed through the SAME descriptor after
        # consumption and must still equal the declared one.
        #
        # This runs only on the normal path, never in `finally`: on an exception the
        # original failure is the one that matters and must not be masked.
        #
        # Cost measured on the real sealed source (0.70 GB): 0.2 s. Once per run.
        os.lseek(fd, 0, os.SEEK_SET)
        post = hashlib.sha256()
        while True:
            chunk = os.read(fd, _HASH_CHUNK)
            if not chunk:
                break
            post.update(chunk)
        post_stat = os.fstat(fd)
        identity_final = (
            post_stat.st_dev,
            post_stat.st_ino,
            post_stat.st_size,
            post_stat.st_mtime_ns,
        )
        post_sha = post.hexdigest()
        if post_sha != expected_sha:
            raise PresealDescriptorError(
                f"sealed source {str(source_path)!r} was modified IN PLACE while it was open: "
                f"the bytes verified before consumption hash to {expected_sha!r} but the same "
                f"descriptor now hashes to {post_sha!r}. The inode is unchanged "
                f"(identity before={identity_after!r} after={identity_final!r}), so a pathname "
                "check could not have seen this. Fail closed: what was consumed is not what was "
                "verified."
            )
        if identity_final != identity_after:
            raise PresealDescriptorError(
                f"sealed source {str(source_path)!r} changed identity while it was open "
                f"(before={identity_after!r} after={identity_final!r}) even though its bytes still "
                "hash to the declared digest. Fail closed rather than reason about how."
            )
    finally:
        os.close(fd)
