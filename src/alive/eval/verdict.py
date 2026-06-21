"""Single authoritative verdict engine — Section-7 truth table (Task 15).

This module implements ``compute_verdict()``, the ONLY function permitted to
emit a scientific verdict.  It encodes the exact precedence truth table from
the CARTOGRAPHER protocol's Section 7:

  1. **INVALID_EVALUATION** — any integrity failure fires first, before
     calibration or gate clauses are examined.
  2. **CALIBRATION_FAILURE** — integrity valid but conformal coverage misses
     the registered acceptance band.
  3. **GATE_WINS** — integrity valid AND calibration valid AND all four gate
     clauses pass simultaneously.
  4. **NO_DISTINCT_WIN** — every other valid completed result.

``VerdictResult`` records a Boolean *and* an evidence value for **every**
clause, regardless of which rule fires, so the output is fully auditable.

Operational statuses ``CONTINUE_CONFIRMATORY`` / ``FUTILITY_STOPPED`` are NOT
scientific verdicts and are never produced here.

Public API
----------
IntegrityReport
    Frozen summary of provenance / leakage / data-sufficiency checks.
VerdictResult
    Frozen verdict with per-clause booleans, evidence, checksum, and I/O.
compute_verdict(integrity, conformal_passes, confirmatory, selected_feature_weight)
    Apply the Section-7 truth table; return a ``VerdictResult``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from alive.provenance import sha256_json

if TYPE_CHECKING:
    from alive.eval.bootstrap import ConfirmatoryInference
    from alive.types import Verdict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _evidence_canonical(value: object) -> object:
    """Convert an evidence value to a JSON-serialisable canonical form.

    Used by both ``VerdictResult.checksum`` and ``VerdictResult.write()`` so
    that ``write()`` → ``read()`` → ``checksum`` is byte-identical:

    - ``bool`` / ``int`` / ``float`` / ``str`` / ``None`` — returned as-is
      (all are JSON-native).
    - ``dict`` — converted to ``repr()`` string for stable, lossless embedding.
    - Anything else — converted via ``repr()``.

    Parameters
    ----------
    value : object
        The raw evidence value to canonicalise.

    Returns
    -------
    object
        A JSON-serialisable representation of *value*.
    """
    if isinstance(value, (bool, int, float, str, type(None))):
        return value
    return repr(value)


# ---------------------------------------------------------------------------
# IntegrityReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrityReport:
    """Summary of all integrity preconditions required before a scientific verdict.

    Parameters
    ----------
    provenance_ok : bool
        Provenance chain is intact (no missing or mismatched hashes).
    leakage_ok : bool
        No data leakage detected between training and sealed evaluation sets.
    sealed_n : int
        Number of items available in the sealed evaluation set.
    minimum_sealed : int
        Registered minimum required for a valid sealed evaluation.
    all_metrics_finite : bool
        All required evaluation metrics are finite (no NaN or ±Inf).
    reliability_ok : bool
        The registered measurement-reliability precondition was satisfied.
    evidence : dict
        Human-readable details (string values are fine) for audit logging.

    Notes
    -----
    ``is_valid`` is the single Boolean gate used by ``compute_verdict``; it is
    the logical AND of all five Boolean fields plus the ``sealed_n`` check.
    """

    provenance_ok: bool
    leakage_ok: bool
    sealed_n: int
    minimum_sealed: int
    all_metrics_finite: bool
    reliability_ok: bool
    evidence: dict

    @property
    def is_valid(self) -> bool:
        """``True`` iff every integrity condition is satisfied.

        Returns
        -------
        bool
        """
        return (
            self.provenance_ok
            and self.leakage_ok
            and self.all_metrics_finite
            and self.reliability_ok
            and self.sealed_n >= self.minimum_sealed
        )


# ---------------------------------------------------------------------------
# VerdictResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictResult:
    """Frozen scientific verdict with full per-clause auditability.

    Parameters
    ----------
    verdict : Verdict
        The scientific verdict emitted by the Section-7 truth table.
    clauses : dict[str, bool]
        One ``bool`` entry per evaluated clause (see ``compute_verdict``
        for the full key list).  Populated for **every** clause regardless
        of which rule fired.
    evidence : dict[str, object]
        Parallel evidence per clause — the underlying raw value or reason that
        determined each clause's Boolean.

    Notes
    -----
    ``checksum`` is a ``cached_property`` that hashes the verdict value,
    clauses, and canonicalised evidence via :func:`~alive.provenance.sha256_json`.
    """

    verdict: "Verdict"
    clauses: dict[str, bool]
    evidence: dict[str, object]

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest of the canonical content of this result.

        Covers ``verdict.value``, ``clauses``, and a canonicalised snapshot of
        ``evidence``.  Evidence values are normalised to a JSON-compatible form
        before hashing so that ``write()`` → ``read()`` → ``checksum`` is
        byte-identical: dict values become ``repr()`` strings (stable, lossless
        for the float/dict/bool/int types used here), and all other values are
        converted via ``repr()`` as well.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        canonical = {
            "verdict": self.verdict.value,
            "clauses": {k: self.clauses[k] for k in sorted(self.clauses)},
            "evidence": {k: _evidence_canonical(self.evidence[k]) for k in sorted(self.evidence)},
        }
        return sha256_json(canonical)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def write(self, path: "str | Path") -> None:
        """Serialise to a JSON file at *path*.

        The output includes ``verdict``, ``clauses``, ``evidence`` (each value
        canonicalised via :func:`_evidence_canonical` for stable round-trip),
        and ``checksum``.  The encoding is deterministic: identical inputs
        produce byte-identical files.

        Parameters
        ----------
        path : str or Path
            Destination file path.  Parent directory must exist.
        """
        payload: dict = {
            "verdict": self.verdict.value,
            "clauses": dict(self.clauses),
            "evidence": {k: _evidence_canonical(v) for k, v in self.evidence.items()},
            "checksum": self.checksum,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        Path(path).write_text(text, encoding="utf-8")

    @classmethod
    def read(cls, path: "str | Path") -> "VerdictResult":
        """Deserialise a :class:`VerdictResult` from a JSON file written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Path to a JSON file produced by :meth:`write`.

        Returns
        -------
        VerdictResult
            A result whose ``.checksum`` equals that of the original.

        Raises
        ------
        ValueError
            If the file is missing required fields or contains an unknown verdict.
        """
        # Import here to avoid circular import at module load time.
        from alive.types import Verdict as _Verdict

        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Failed to read VerdictResult from {path!r}: {exc}") from exc

        try:
            verdict = _Verdict(raw["verdict"])
            clauses: dict[str, bool] = {k: bool(v) for k, v in raw["clauses"].items()}
            # Evidence is stored in canonical form (via _evidence_canonical in write()).
            # Load as-is: the checksum on the loaded object will use _evidence_canonical
            # on the already-canonical values, which is a no-op for JSON-native types
            # (bool/int/float/str/None) and repr() for dicts (stored as repr strings).
            evidence: dict[str, object] = dict(raw["evidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"VerdictResult JSON is malformed: {exc}") from exc

        return cls(verdict=verdict, clauses=clauses, evidence=evidence)


# ---------------------------------------------------------------------------
# compute_verdict — Section-7 truth table
# ---------------------------------------------------------------------------


def compute_verdict(
    integrity: IntegrityReport,
    conformal_passes: bool,
    confirmatory: "ConfirmatoryInference",
    selected_feature_weight: float,
) -> VerdictResult:
    """Apply the Section-7 truth table and return a fully auditable verdict.

    Precedence (first matching rule wins):

    1. **INVALID_EVALUATION** if ``integrity.is_valid`` is ``False``
       (provenance/leakage failure, ``sealed_n < minimum_sealed``, any required
       metric non-finite, or measurement-reliability precondition failed).
    2. **CALIBRATION_FAILURE** if integrity is valid but ``conformal_passes``
       is ``False``.
    3. **GATE_WINS** if integrity valid AND calibration valid AND ALL of:
       - ``confirmatory.aurc_family_passes`` is ``True``,
       - ``confirmatory.augrc_no_material_degradation`` is ``True``,
       - ``confirmatory.added_value_passes`` is ``True``,
       - ``selected_feature_weight > 0``.
    4. **NO_DISTINCT_WIN** otherwise.

    All eleven clause keys are recorded in ``clauses`` and ``evidence``
    regardless of which rule fired, enabling complete post-hoc auditability.

    Parameters
    ----------
    integrity : IntegrityReport
        Provenance / leakage / sufficiency pre-checks.
    conformal_passes : bool
        ``True`` iff the scalar error-bound coverage meets the registered
        acceptance band (caller computes this via
        ``conformal_coverage_passes(...)``).
    confirmatory : ConfirmatoryInference
        Frozen simultaneous bootstrap inference results from Task 14.
        Consumed fields: ``aurc_family_passes``,
        ``augrc_no_material_degradation``, ``added_value_passes``.
    selected_feature_weight : float
        The selected full-gate feature weight.  Must be ``> 0`` for a gate win.

    Returns
    -------
    VerdictResult
        Frozen result with ``verdict``, ``clauses``, ``evidence``, and
        ``checksum``.  A fixed set of inputs always produces an identical
        ``checksum``.
    """
    # Import here to avoid circular import at module level.
    from alive.types import Verdict

    # ------------------------------------------------------------------
    # 1. Evaluate EVERY clause unconditionally (full auditability)
    # ------------------------------------------------------------------
    sealed_n_ok: bool = integrity.sealed_n >= integrity.minimum_sealed
    integrity_valid: bool = integrity.is_valid

    feature_weight_positive: bool = selected_feature_weight > 0.0

    clauses: dict[str, bool] = {
        "provenance_ok": integrity.provenance_ok,
        "leakage_ok": integrity.leakage_ok,
        "sealed_n_ok": sealed_n_ok,
        "metrics_finite": integrity.all_metrics_finite,
        "reliability_ok": integrity.reliability_ok,
        "integrity_valid": integrity_valid,
        "conformal_passes": bool(conformal_passes),
        "aurc_family_passes": confirmatory.aurc_family_passes,
        "augrc_no_material_degradation": confirmatory.augrc_no_material_degradation,
        "added_value_passes": confirmatory.added_value_passes,
        "feature_weight_positive": feature_weight_positive,
    }

    # Evidence: the concrete underlying value/reason for each clause.
    evidence: dict[str, object] = {
        "provenance_ok": integrity.provenance_ok,
        "leakage_ok": integrity.leakage_ok,
        # Record sealed_n so reviewers can see the raw count.
        "sealed_n_ok": integrity.sealed_n,
        "metrics_finite": integrity.all_metrics_finite,
        "reliability_ok": integrity.reliability_ok,
        "integrity_valid": integrity.evidence,
        "conformal_passes": bool(conformal_passes),
        "aurc_family_passes": confirmatory.aurc_family_passes,
        "augrc_no_material_degradation": confirmatory.augrc_no_material_degradation,
        "added_value_passes": confirmatory.added_value_passes,
        "feature_weight_positive": float(selected_feature_weight),
    }

    # ------------------------------------------------------------------
    # 2. Apply truth table in strict precedence order
    # ------------------------------------------------------------------

    # Rule 1: INVALID_EVALUATION (integrity first — checked before calibration
    # or gate clauses, even if everything else would pass)
    if not integrity_valid:
        verdict = Verdict.INVALID_EVALUATION

    # Rule 2: CALIBRATION_FAILURE (integrity valid but conformal miss)
    elif not conformal_passes:
        verdict = Verdict.CALIBRATION_FAILURE

    # Rule 3: GATE_WINS (all four gate clauses must pass simultaneously)
    elif (
        confirmatory.aurc_family_passes
        and confirmatory.augrc_no_material_degradation
        and confirmatory.added_value_passes
        and feature_weight_positive
    ):
        verdict = Verdict.GATE_WINS

    # Rule 4: NO_DISTINCT_WIN (valid, calibrated, but gate not cleared)
    else:
        verdict = Verdict.NO_DISTINCT_WIN

    return VerdictResult(verdict=verdict, clauses=clauses, evidence=evidence)
