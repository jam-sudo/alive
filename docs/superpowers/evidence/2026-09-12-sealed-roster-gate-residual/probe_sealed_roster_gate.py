"""Does the lock validator bind the declared sealed roster to the canonical split?

Run from the repository root::

    PYTHONPATH=src .venv/bin/python \
      docs/superpowers/evidence/2026-09-12-sealed-roster-gate-residual/probe_sealed_roster_gate.py

Three arms, because one arm measures nothing. A validator that refused everything
would "pass" arm A alone, and a validator that accepted everything would "pass"
arm B alone; only the pair distinguishes a binding from its absence.

  A  hand-written roster that hides a genuinely sealed pair   -> expected: ACCEPTED (the residual)
  B  control: the same training roster, sealed declared fully -> expected: REFUSED
  C  ground truth: the split manifest verifies and names the hidden pair as sealed

Arm C is what makes A a defect rather than an opinion: the canonical answer exists,
is self-verifying, and the validator simply never consults it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from alive.compose.activation_evidence import (
    _PROTOCOL,
    ActivationEvidenceError,
    _validate_pair_roster_manifest,
)
from alive.compose.roles import SEALED_ROLE_NAMES
from alive.compose.split import build_pair_split, build_split_manifest, verify_split_manifest
from alive.provenance import sha256_json

SEED = 0
CALIBRATION_FRACTION = 0.25


def _token(pair) -> str:
    """Byte-ordered ``A_B``, the encoding the smoke roster stores combos in."""
    a, b = str(pair[0]), str(pair[1])
    first, second = (a, b) if a.encode("utf-8") < b.encode("utf-8") else (b, a)
    return f"{first}_{second}"


def _handwritten(training: list[str], sealed: list[str]) -> tuple[dict, dict]:
    """A roster manifest and run-gate record built WITHOUT the producer.

    Every internal-consistency obligation is satisfied: exact key roster, schema and
    protocol identity, the exact fit roster roles, sorted unique lists, a correct
    self-excluding ``manifest_checksum`` and record hashes taken from these lists.
    Nothing here is malformed -- that is the point.
    """
    roster = {
        "schema": "compose_smoke_pair_roster_v1",
        "protocol": _PROTOCOL,
        "backend": "gears",
        "training_roles": ["singles", "combo_calibration"],
        "training_pair_ids": sorted(set(training)),
        "sealed_pair_ids": sorted(set(sealed)),
    }
    roster["manifest_checksum"] = sha256_json(roster)
    record = {
        "training_pair_roster_sha256": sha256_json(roster["training_pair_ids"]),
        "sealed_pair_roster_sha256": sha256_json(roster["sealed_pair_ids"]),
        "sealed_pair_overlap_count": len(
            set(roster["training_pair_ids"]) & set(roster["sealed_pair_ids"])
        ),
    }
    return roster, record


def _accepts(label: str, training: list[str], sealed: list[str]) -> bool:
    roster, record = _handwritten(training, sealed)
    path = Path(tempfile.mkdtemp()) / "roster.json"
    path.write_text(json.dumps(roster), encoding="utf-8")
    try:
        _validate_pair_roster_manifest(path, backend="gears", record=record)
    except ActivationEvidenceError as exc:
        print(f"  {label}: REFUSED  -- {exc}")
        return False
    print(f"  {label}: ACCEPTED (sealed_pair_overlap_count={record['sealed_pair_overlap_count']})")
    return True


def main() -> int:
    genes = [f"G{i:02d}" for i in range(12)]
    pairs = [(a, b) for i, a in enumerate(genes) for b in genes[i + 1 :]][:30]
    split = build_pair_split(pairs, seed=SEED, calibration_fraction=CALIBRATION_FRACTION)
    manifest = build_split_manifest(
        pairs, split, seed=SEED, calibration_fraction=CALIBRATION_FRACTION
    )

    canonical_sealed = sorted(
        {_token(p) for role in SEALED_ROLE_NAMES for p in manifest["roles"][role]}
    )
    canonical_training = sorted({_token(p) for p in split.combo_calibration})
    hidden = canonical_sealed[0]

    print(f"canonical split: training={len(canonical_training)} sealed={len(canonical_sealed)}")
    print(f"pair hidden from the declaration: {hidden}\n")

    print("A  hidden: a genuinely sealed pair is trained on and left out of the declaration")
    accepted_hidden = _accepts(
        "A", canonical_training + [hidden], [s for s in canonical_sealed if s != hidden]
    )

    print("\nB  control: same training roster, the declaration names every sealed pair")
    accepted_honest = _accepts("B", canonical_training + [hidden], canonical_sealed)

    print("\nC  ground truth: the split manifest verifies and names the hidden pair as sealed")
    checksum = verify_split_manifest(dict(manifest))
    in_sealed = hidden in canonical_sealed
    print(f"  C: verify_split_manifest -> {checksum[:16]}…  hidden_is_sealed={in_sealed}")

    residual = accepted_hidden and not accepted_honest and in_sealed
    print(
        "\nverdict: "
        + (
            "RESIDUAL CONFIRMED -- concealment passes, honest declaration is refused, "
            "and the canonical answer was available all along."
            if residual
            else "not reproduced -- the gate now binds the declaration to the split."
        )
    )
    return 0 if residual else 1


if __name__ == "__main__":
    raise SystemExit(main())
