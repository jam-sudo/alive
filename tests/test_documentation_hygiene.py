"""Repository-wide documentation portability and current-state guards."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\[\]\n]+\]\(([^)\n]+)\)")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
CURRENT_ENTRYPOINTS = (
    ROOT / "README.md",
    ROOT / "CLAUDE.md",
    ROOT / "docs/superpowers/COMPOSE-SEAL-READINESS.md",
    ROOT / "docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md",
    ROOT / "docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md",
)


def _repository_markdown() -> list[Path]:
    try:
        output = subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "*.md",
            ],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        ignored_parts = {".git", ".venv", ".superpowers", "__pycache__"}
        return sorted(
            path for path in ROOT.rglob("*.md") if not ignored_parts.intersection(path.parts)
        )
    return [ROOT / name for name in output.split("\0") if name]


def _target_path(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    # Markdown permits an optional quoted title after the destination.
    return re.split(r"\s+(?=[\"'])", target, maxsplit=1)[0]


def test_repository_markdown_links_are_portable_and_resolve() -> None:
    absolute: list[str] = []
    missing: list[str] = []
    for document in _repository_markdown():
        for line_number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for match in MARKDOWN_LINK.finditer(line):
                # A function call such as ``name[arg](...)`` inside inline code is not a link.
                if line[: match.start()].count("`") % 2:
                    continue
                target = _target_path(match.group(1))
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                if target.startswith(("file://", "vscode://", "/")) or WINDOWS_ABSOLUTE.match(
                    target
                ):
                    absolute.append(f"{document.relative_to(ROOT)}:{line_number}: {target}")
                    continue
                local_target = unquote(target.split("#", maxsplit=1)[0])
                if local_target and not (document.parent / local_target).resolve().exists():
                    missing.append(f"{document.relative_to(ROOT)}:{line_number}: {target}")
    assert not absolute, "non-portable local links:\n" + "\n".join(absolute)
    assert not missing, "broken relative links:\n" + "\n".join(missing)


def test_current_compose_entrypoints_use_three_axis_state() -> None:
    for document in CURRENT_ENTRYPOINTS:
        text = document.read_text(encoding="utf-8")
        assert "ACTIVE" in text, document
        assert "RELEASE-BLOCKED" in text, document
        assert "UNOPENED" in text, document
