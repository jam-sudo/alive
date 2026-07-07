"""Shared builder for a minimal VALID v2 COMPLETE / INVALID terminal report body.

D1 Task 3 CLOSED the ``COMPLETE`` / ``INVALID`` terminal roster to the exact
state-specific fields (spec §2.1): the outcome-free ``registered_summary`` + its
canonical ``terminal_embedded_provenance`` plus the four layered content
checksums. Unit tests that drive :meth:`alive.compose.terminal.Phase2bTerminal.
complete` / :meth:`~alive.compose.terminal.Phase2bTerminal.invalid` DIRECTLY
(rather than through the orchestrator, which builds the real body) construct their
state-specific body here so the single canonical shape is shared across the
terminal + seal-boundary unit tests and cannot drift.

SYNTHETIC-ONLY: placeholder-but-finite scalars and hex-string checksums; no real
Norman data, no seal, no sealed outcome.
"""

from __future__ import annotations

from alive.provenance import sha256_json

_EVALUATION_PAYLOAD_CHECKSUM = "1" * 64
_FINAL_VERDICT_CHECKSUM = "2" * 64
_PROVENANCE_CHECKSUM = "c" * 64


def minimal_registered_summary(**overrides: object) -> dict:
    """A minimal VALID outcome-free registered summary (finite floats only)."""
    summary: dict = {
        "protocol": "COMPOSE-K562-v1",
        "run_id": "run-fixture",
        "terminal_state": "COMPLETE",
        "sealed_access_count": 1,
        "sample_counts": {"double": 4, "single": 4},
        "per_method_aggregate_mse": {"l1_bilinear_identifiable": 0.40, "additive": 0.55},
        "theta": {"additive": 0.42},
        "simultaneous_lower_bounds": {"additive": 0.10},
        "family_confidence": 0.95,
        "bootstrap_replicates": 3,
        "gi_explained_point": 0.12,
        "gi_explained_interval": [0.05, 0.20],
        "gi_structure_recovery": "NOT_EVALUABLE",
        "sealed_axis": "NO_DISTINCT_WIN",
        "method_axis": "METHOD_VALIDATED",
        "verdict_clauses": {"integrity_valid": True},
        "integrity_disclaimer": "structural run-internal self-check only",
        "bundle_checksum": "a" * 64,
        "manifest_checksum": "b" * 64,
        "provenance_checksum": _PROVENANCE_CHECKSUM,
        "regime_result_double_checksum": "d" * 64,
        "regime_result_single_checksum": "e" * 64,
        "bounds_checksum": "f" * 64,
        "seed_variability_report_checksum": "0" * 64,
    }
    summary.update(overrides)
    return summary


def minimal_v2_terminal_body(**summary_overrides: object) -> dict:
    """Build the exact COMPLETE / INVALID state roster (spec §2.1) for a unit test.

    Returns only the seven state-specific fields; the terminal writer injects the
    common identity roster and the self-excluding ``terminal_payload_checksum``, and
    :meth:`~alive.compose.terminal.Phase2bTerminal.complete` /
    :meth:`~alive.compose.terminal.Phase2bTerminal.invalid` set the top-level
    ``terminal_state``. ``summary_overrides`` are applied to the embedded summary
    (e.g. ``theta=float("nan")`` to exercise the non-finite guard).
    """
    summary = minimal_registered_summary(**summary_overrides)
    registered_summary_checksum = sha256_json(summary)
    final_result_checksum = sha256_json(
        {
            "terminal_state": summary["terminal_state"],
            "final_verdict_checksum": _FINAL_VERDICT_CHECKSUM,
            "registered_summary_checksum": registered_summary_checksum,
            "evaluation_payload_checksum": _EVALUATION_PAYLOAD_CHECKSUM,
            "provenance_checksum": _PROVENANCE_CHECKSUM,
        }
    )
    return {
        "registered_summary": summary,
        "registered_summary_checksum": registered_summary_checksum,
        "final_verdict_checksum": _FINAL_VERDICT_CHECKSUM,
        "terminal_embedded_provenance": {"schema": "compose_phase2b_provenance_v2"},
        "provenance_checksum": _PROVENANCE_CHECKSUM,
        "evaluation_payload_checksum": _EVALUATION_PAYLOAD_CHECKSUM,
        "final_result_checksum": final_result_checksum,
    }
