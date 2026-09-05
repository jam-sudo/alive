"""Produce the dev-pod smoke evidence that :mod:`alive.compose.activation_evidence` demands.

The validator is strict and complete; what was missing is a producer. Until now the
dependency lock's ``run_gate.required_evidence`` had to be filled in by hand on the
pod, which is exactly how a measurement and its record drift apart -- this
repository's dominant defect, and the reason the lock still reads
``activation=BLOCKED`` / ``evidence_status=INCOMPLETE``.

Every cross-check the validator performs is derived here from ONE computation, so
the two sides cannot disagree. The schema/protocol/role strings are spelled here
rather than imported: ``activation_evidence`` is a member of the frozen
kernel-isolation closure, so no public constant may be added to it, and reaching
for its private names would bind to a name rather than to the contract. The
round-trip tests bind them instead -- a wrong string is refused by the committed
validator itself.
"""

from __future__ import annotations

from typing import Any

from alive.provenance import sha256_json

__all__ = ["PAIR_ROSTER_SCHEMA", "build_smoke_pair_roster"]

PAIR_ROSTER_SCHEMA = "compose_smoke_pair_roster_v1"
_PROTOCOL = "COMPOSE-K562-v1"
_TRAINING_ROLES = ["singles", "combo_calibration"]


def build_smoke_pair_roster(
    *,
    backend: str,
    training_pair_ids: list[str],
    sealed_pair_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a pair-roster manifest and the run-gate record fields bound to it.

    Parameters
    ----------
    backend : str
        ``"gears"`` or ``"cpa"``; must match the record's position in the lock.
    training_pair_ids : list of str
        Pair IDs the smoke actually fits on. Sorted and de-duplicated here so the
        caller cannot hand the validator a non-canonical roster; the record's
        hashes are taken from the same normalised list the manifest carries.
    sealed_pair_ids : list of str
        Pair IDs the protocol seals; present only so the disjointness can be measured.
        Normalised the same way.

    Returns
    -------
    tuple of (dict, dict)
        The ``compose_smoke_pair_roster_v1`` manifest, and the fragment of
        ``run_gate.required_evidence[backend]`` that the manifest determines.
    """
    roster: dict[str, Any] = {
        "schema": PAIR_ROSTER_SCHEMA,
        "protocol": _PROTOCOL,
        "backend": backend,
        "training_roles": list(_TRAINING_ROLES),
        "training_pair_ids": sorted(set(training_pair_ids)),
        "sealed_pair_ids": sorted(set(sealed_pair_ids)),
    }
    roster["manifest_checksum"] = sha256_json(roster)
    record: dict[str, Any] = {
        "training_pair_roster_sha256": sha256_json(roster["training_pair_ids"]),
        "sealed_pair_roster_sha256": sha256_json(roster["sealed_pair_ids"]),
        "sealed_pair_overlap_count": len(
            set(roster["training_pair_ids"]) & set(roster["sealed_pair_ids"])
        ),
    }
    return roster, record
