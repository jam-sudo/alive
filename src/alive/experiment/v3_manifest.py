"""Intake-manifest validation for CART-K562-V3.1 (lab metadata only; no file-format reader).

The independent unit is the lentiviral transduction. The validator rejects a manifest that
cannot prove separate cultures and separate 10x lanes per transduction, or whose guide table
does not match the registered roster. It reads no expression data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

TRANSDUCTION_FIELDS = ("transduction_id", "culture_id", "transduction_date", "virus_lot")
LIBRARY_FIELDS = ("library_id", "transduction_id", "lane_id")
NON_TARGETING = "non-targeting"


def _text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _records(manifest: Mapping, key: str, fields: tuple[str, ...], errors: list[str]) -> list:
    recs = manifest.get(key)
    if not isinstance(recs, list) or not recs:
        errors.append(f"{key}: missing or empty")
        return []
    good = []
    for i, r in enumerate(recs):
        bad = [f for f in fields if not (isinstance(r, Mapping) and _text(r.get(f)))]
        if bad:
            errors.append(f"{key}[{i}]: missing/blank {bad}")
        else:
            good.append(r)
    return good


def _dupes(values) -> list:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def validate_intake_manifest(
    manifest: Mapping,
    roster: Mapping,
    *,
    protocol_id: str,
    roster_sha256: str,
    cell_line: str,
    min_units: int,
) -> None:
    """Raise ``ValueError`` listing every problem; return ``None`` if the manifest is valid.

    Parameters
    ----------
    manifest : mapping
        Lab-supplied intake manifest (``protocol_id``, ``roster_sha256``, ``cell_line``,
        ``transductions``, ``libraries``, ``guides``).
    roster : mapping
        The registered target roster (``targets`` with ``target`` and ``gwps_guide_ids``).
    protocol_id, roster_sha256, cell_line, min_units
        Registered values from the protocol config.
    """
    errors: list[str] = []
    if manifest.get("protocol_id") != protocol_id:
        errors.append(f"protocol_id {manifest.get('protocol_id')!r} != {protocol_id!r}")
    if manifest.get("roster_sha256") != roster_sha256:
        errors.append("roster_sha256 does not match the registered roster")
    cl = manifest.get("cell_line")
    if not (
        isinstance(cl, Mapping)
        and cl.get("name") == cell_line
        and _text(cl.get("authentication_id"))
    ):
        errors.append(f"cell_line must be {cell_line!r} with a non-blank authentication_id")

    tds = _records(manifest, "transductions", TRANSDUCTION_FIELDS, errors)
    td_ids = [t["transduction_id"] for t in tds]
    if d := _dupes(td_ids):
        errors.append(f"duplicate transduction_id {d}")
    if d := _dupes(t["culture_id"] for t in tds):
        errors.append(f"culture shared by transductions (not independent): {d}")
    if len(set(td_ids)) < min_units:
        errors.append(f"{len(set(td_ids))} independent transductions < registered {min_units}")

    libs = _records(manifest, "libraries", LIBRARY_FIELDS, errors)
    if d := _dupes(lib["library_id"] for lib in libs):
        errors.append(f"duplicate library_id {d}")
    if d := _dupes(lib["lane_id"] for lib in libs):
        errors.append(f"10x lane used by more than one library (lanes must be separate): {d}")
    if unknown := sorted({lib["transduction_id"] for lib in libs} - set(td_ids)):
        errors.append(f"libraries reference unknown transductions {unknown}")
    if empty := sorted(set(td_ids) - {lib["transduction_id"] for lib in libs}):
        errors.append(f"transductions without a library {empty}")

    guides = _records(manifest, "guides", ("guide_id", "target"), errors)
    if d := _dupes(g["guide_id"] for g in guides):
        errors.append(f"duplicate guide_id {d}")
    mapped = {g["guide_id"]: g["target"] for g in guides}
    expected = {gid: r["target"] for r in roster["targets"] for gid in r["gwps_guide_ids"]}
    if missing := sorted(set(expected) - set(mapped)):
        errors.append(f"{len(missing)} roster guides missing, e.g. {missing[:3]}")
    if wrong := sorted(g for g in set(expected) & set(mapped) if mapped[g] != expected[g]):
        errors.append(f"guides mapped to the wrong target {wrong[:3]}")
    extra = {g: t for g, t in mapped.items() if g not in expected and t != NON_TARGETING}
    if extra:
        errors.append(f"{len(extra)} guides outside the roster, e.g. {sorted(extra)[:3]}")
    if NON_TARGETING not in mapped.values():
        errors.append("no non-targeting control guides")

    if errors:
        raise ValueError("invalid V3.1 intake manifest:\n- " + "\n- ".join(errors))
