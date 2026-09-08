"""`alive.io.atomic_write_once` -- the write-once primitive CLAUDE.md 4.3 names as
an enforcement point.

It had no dedicated module until 2026-09-07 (audit F-A5); its behaviour was only reached through
test_terminal / test_freeze / test_outcome_store.
"""

from __future__ import annotations

import pytest

from alive.io import atomic_write_once


def test_a_second_write_to_the_same_destination_is_refused(tmp_path):
    target = tmp_path / "once.json"
    atomic_write_once(target, '{"a": 1}')
    with pytest.raises(FileExistsError):
        atomic_write_once(target, '{"a": 2}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'


def test_the_refused_write_leaves_no_temporary_file_behind(tmp_path):
    target = tmp_path / "once.json"
    atomic_write_once(target, "first")
    with pytest.raises(FileExistsError):
        atomic_write_once(target, "second")
    assert [p.name for p in tmp_path.iterdir() if p.name != "once.json"] == []


def test_publication_is_by_link_so_the_destination_is_never_replaced(tmp_path):
    target = tmp_path / "once.json"
    atomic_write_once(target, "first")
    inode_before = target.stat().st_ino
    with pytest.raises(FileExistsError):
        atomic_write_once(target, "second")
    assert target.stat().st_ino == inode_before
