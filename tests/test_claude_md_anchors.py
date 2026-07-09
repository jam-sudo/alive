"""CLAUDE.md cross-reference integrity (P2 anchor checker).

Governance code and docs point at CLAUDE.md by stable ``#anchor`` slugs
(e.g. ``CLAUDE.md#seal``) rather than by fragile section numbers. A CLAUDE.md
refactor that renumbers sections used to silently break ~100 ``CLAUDE.md §N``
references; anchors are immune to renumbering, and these tests make the anchor
contract self-enforcing:

1. **Anchor resolution** — every ``CLAUDE.md#<slug>`` reference anywhere in the
   repo resolves to a ``{#<slug>}`` anchor defined in CLAUDE.md. Deleting or
   renaming an anchor without updating its referrers fails this test.
2. **No fragile numbering in code** — the code layer (``src/``, ``tests/``,
   ``scripts/``, ``configs/``) carries no ``CLAUDE.md §<number>`` references.
   Historical docs (audits, superseded specs, branch-divergent loop docs) may
   legitimately retain old section numbers, so the numbering guard is scoped to
   code only.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"

TEXT_EXT = {".py", ".md", ".yaml", ".yml", ".txt", ".cfg", ".toml", ".sh"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", ".superpowers"}
CODE_DIRS = ("src", "tests", "scripts", "configs")

# `CLAUDE.md` (optionally backtick-wrapped) followed by one or more #anchor slugs
# joined by whitespace / , / · (captures continuations like `#seal / #provenance`).
ANCHOR_REF = re.compile(r"`{0,2}CLAUDE\.md`{0,2}((?:#[a-z0-9-]+[\s,/·]*)+)")
SLUG = re.compile(r"#([a-z0-9-]+)")
# `CLAUDE.md` followed by a §number (the fragile form we migrated away from).
NUMERIC_REF = re.compile(r"`{0,2}CLAUDE\.md`{0,2}\s+§\d")


def _iter_text_files(base: Path):
    for p in base.rglob("*"):
        if p.is_file() and p.suffix in TEXT_EXT and not (SKIP_DIRS & set(p.parts)):
            if p.name == "CLAUDE.md.bak":
                continue
            yield p


def _defined_anchors() -> set[str]:
    return set(re.findall(r"\{#([a-z0-9-]+)\}", CLAUDE_MD.read_text(encoding="utf-8")))


def test_every_claude_md_anchor_reference_resolves():
    anchors = _defined_anchors()
    assert anchors, "no {#anchor} definitions found in CLAUDE.md"
    dangling: dict[str, list[str]] = {}
    for f in _iter_text_files(ROOT):
        if f == CLAUDE_MD:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for grp in ANCHOR_REF.findall(text):
            for slug in SLUG.findall(grp):
                if slug not in anchors:
                    dangling.setdefault(str(f.relative_to(ROOT)), []).append(slug)
    assert not dangling, (
        "CLAUDE.md #<slug> references with no matching {#slug} in CLAUDE.md:\n"
        + "\n".join(f"  {f}: {sorted(set(s))}" for f, s in sorted(dangling.items()))
        + f"\ndefined anchors: {sorted(anchors)}"
    )


def test_code_layer_has_no_fragile_section_number_refs():
    offenders: dict[str, int] = {}
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for f in _iter_text_files(base):
            hits = len(NUMERIC_REF.findall(f.read_text(encoding="utf-8", errors="ignore")))
            if hits:
                offenders[str(f.relative_to(ROOT))] = hits
    assert not offenders, (
        "fragile `CLAUDE.md §N` refs in the code layer (use stable #anchors instead):\n"
        + "\n".join(f"  {f}: {n}" for f, n in sorted(offenders.items()))
    )
