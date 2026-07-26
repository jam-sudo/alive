"""COMPOSE-K562-v1 Phase-2b EXACT-ROSTER sealed verdict (Task 2b-5).

SYNTHETIC-ONLY: pure decision logic — this module touches **no** seal, **no**
outcome store and **no** real Norman data. It maps the headline DOUBLE-UNSEEN
simultaneous lower bounds (computed elsewhere by
:func:`alive.compose.inference2.simultaneous_theta_bounds`) onto the registered
COMPOSE sealed-axis verdict, over the EXACT registered comparator family.

Why COMPOSE-specific verdict types (not CARTOGRAPHER's)
-------------------------------------------------------
``CLAUDE.md`` #seal (multiple-seal rule): a COMPOSE run ID, audit file or result
can never represent a CARTOGRAPHER seal, and vice versa. So this module defines
its **own** sealed/method enums (:class:`SealedAxis`, :class:`MethodAxis`),
its own :class:`ComposeIntegrityReport`, and its own
:class:`ComposeSealedResult`. It deliberately does **not** reuse
``alive.eval.verdict.IntegrityReport`` / ``VerdictResult`` or
``alive.types.Verdict`` (those are CARTOGRAPHER's). It *mirrors* the
``VerdictResult`` per-clause-auditability pattern (every evaluated clause
recorded as a ``bool`` + parallel evidence + content checksum) but shares no
type with it.

Two separate axes
-----------------
The verdict reports two orthogonal axes:

* the **sealed axis** (:class:`SealedAxis`) — the registered GI-learnability
  outcome on the real sealed double-unseen contrast, decided ONLY from the
  simultaneous lower bounds and the integrity report;
* the **method axis** (:class:`MethodAxis`) — whether the operator was validated
  as identifiable (e.g. from the Phase-1 synthetic recovery proof), supplied as
  an INPUT.

``METHOD_VALIDATED`` is method-level evidence on synthetic data only. It is
NEVER described as, nor allowed to upgrade, evidence of real generalization: the
two axes are decided independently and the result carries an explicit caveat to
that effect.

Decision logic (strict inequalities at exactly the registered thresholds)
-------------------------------------------------------------------------
Let ``learned_family = comparators \\ {"additive"}`` (non-empty: an empty
learned family is an ERROR, never a win)::

    additive_clears     = bounds.lower["additive"] > additive_margin   # 0.05
    every_learned_beats = all(bounds.lower[c] > learned_margin          # 0.0
                              for c in learned_family)

    if not integrity.is_valid:                  -> INVALID   (integrity dominates)
    elif additive_clears and every_learned_beats -> GI_LEARNABLE_WIN
    elif additive_clears and not every_learned_beats -> PARTIAL
    else                                         -> NO_DISTINCT_WIN

Only the DOUBLE-UNSEEN regime may enter this function. The single-unseen regime
(or anything else) fails closed (raises) — single-unseen results cannot drive
this verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from pathlib import Path

from alive.compose.roles import SEALED_DOUBLE_UNSEEN_ROLE_NAME
from alive.provenance import sha256_json

# Registered double-unseen role name (config ``split.roles``); the ONLY regime
# permitted to drive this verdict.
DOUBLE_UNSEEN_ROLE: str = SEALED_DOUBLE_UNSEEN_ROLE_NAME

# Registered integrity-clause disclaimer (config ``verdict.integrity_clause_
# disclaimer``). Carried verbatim into the result evidence so reviewers can see
# that the integrity clauses are a run-internal self-check, NOT an audit.
INTEGRITY_CLAUSE_DISCLAIMER: str = "structural run-internal self-check, NOT an independent audit"

# The headline method (config ``baselines.ablation_ladder[0]``); never a
# comparator and never an "additive" key.
_HEADLINE_METHOD: str = "l1_bilinear_identifiable"


class ComposeVerdictError(ValueError):
    """Raised on any invalid input to :func:`sealed_verdict`.

    Distinct from CARTOGRAPHER's exception types so COMPOSE callers can catch
    COMPOSE-specific verdict failures without coupling to the other protocol.
    """


class SealedAxis(str, Enum):
    """COMPOSE Phase-2b sealed-axis verdict (config ``verdict.sealed_axis``).

    Members
    -------
    GI_LEARNABLE_WIN
        The headline simultaneously beats the additive baseline by the material
        margin AND every registered learned comparator by the learned margin.
    PARTIAL
        The headline clears the additive material margin but fails to beat every
        learned comparator simultaneously.
    NO_DISTINCT_WIN
        The headline does not clear the additive material margin.
    FUTILITY_STOPPED
        Reserved development-stop status (never produced by :func:`sealed_verdict`,
        which is a confirmatory sealed-axis decision, but registered for
        completeness of the axis).
    INVALID
        Integrity precondition failed; dominates all bound-based outcomes.
    """

    GI_LEARNABLE_WIN = "GI_LEARNABLE_WIN"
    PARTIAL = "PARTIAL"
    NO_DISTINCT_WIN = "NO_DISTINCT_WIN"
    FUTILITY_STOPPED = "FUTILITY_STOPPED"
    INVALID = "INVALID"


class MethodAxis(str, Enum):
    """COMPOSE Phase-2b method-axis value (config ``verdict.method_axis``).

    This axis records whether the operator was validated as identifiable (e.g.
    from the Phase-1 synthetic recovery proof). ``METHOD_VALIDATED`` is method
    -level evidence only and is NEVER evidence of real generalization.

    Members
    -------
    METHOD_VALIDATED
        The identifiable-operator method was validated (synthetic recovery).
    METHOD_NOT_VALIDATED
        The method was not validated.
    """

    METHOD_VALIDATED = "METHOD_VALIDATED"
    METHOD_NOT_VALIDATED = "METHOD_NOT_VALIDATED"


# ---------------------------------------------------------------------------
# Integrity report (COMPOSE-specific; structural run-internal self-check)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComposeIntegrityReport:
    """COMPOSE structural integrity preconditions for the sealed verdict.

    This is a STRUCTURAL run-internal self-check — NOT an independent audit (see
    ``disclaimer``). ``is_valid`` is the single boolean gate consumed by
    :func:`sealed_verdict`; when it is ``False`` the verdict is ``INVALID``
    regardless of the simultaneous bounds.

    Parameters
    ----------
    provenance_ok : bool
        Provenance chain is intact (no missing or mismatched hashes).
    leakage_ok : bool
        No leakage between fit/calibration roles and the sealed double-unseen
        contrast.
    all_metrics_finite : bool
        Every required metric / bound is finite (no NaN or ±Inf).
    sealed_access_consistent : bool
        The recorded sealed-access lifecycle is consistent (the sealed
        double-unseen contrast was opened exactly as the write-once protocol
        requires).
    sealed_n : int
        Number of pairs scored in the sealed double-unseen contrast.
    minimum_sealed : int
        Registered minimum required for a valid sealed evaluation.
    disclaimer : str
        Versioned disclaimer string carried into the result evidence. Defaults to
        the registered config disclaimer.
    """

    provenance_ok: bool
    leakage_ok: bool
    all_metrics_finite: bool
    sealed_access_consistent: bool
    sealed_n: int
    minimum_sealed: int
    disclaimer: str = INTEGRITY_CLAUSE_DISCLAIMER

    @property
    def is_valid(self) -> bool:
        """``True`` iff every integrity clause and the ``sealed_n`` check pass.

        Returns
        -------
        bool
            Logical AND of all boolean clauses with ``sealed_n >= minimum_sealed``.
        """
        return (
            self.provenance_ok
            and self.leakage_ok
            and self.all_metrics_finite
            and self.sealed_access_consistent
            and self.sealed_n >= self.minimum_sealed
        )


# ---------------------------------------------------------------------------
# Sealed result (mirrors the VerdictResult per-clause-auditability pattern)
# ---------------------------------------------------------------------------


def _evidence_canonical(value: object) -> object:
    """Convert an evidence value to a stable JSON-serialisable canonical form.

    JSON-native scalars (``bool``/``int``/``float``/``str``/``None``) pass
    through; everything else (e.g. the per-learned-comparator dict) becomes a
    ``repr()`` string so the checksum is stable and lossless.

    Parameters
    ----------
    value : object
        Raw evidence value.

    Returns
    -------
    object
        JSON-serialisable representation of *value*.
    """
    if isinstance(value, (bool, int, float, str, type(None))):
        return value
    return repr(value)


@dataclass(frozen=True)
class ComposeSealedResult:
    """Frozen COMPOSE sealed verdict reporting the two axes separately.

    Mirrors CARTOGRAPHER's ``VerdictResult`` per-clause auditability (a ``bool``
    for every evaluated clause plus parallel evidence and a content checksum) but
    is a distinct COMPOSE-specific type (``CLAUDE.md`` #seal).

    Parameters
    ----------
    sealed_axis : SealedAxis
        The sealed-axis verdict on the real double-unseen contrast.
    method_axis : MethodAxis
        The method-axis value (an INPUT; e.g. Phase-1 synthetic identifiability).
        Reported independently; never upgraded by the sealed axis.
    clauses : dict[str, bool]
        One ``bool`` per evaluated clause (``integrity_valid``,
        ``additive_clears``, ``every_learned_beats``), populated regardless of
        which rule fired — no single-metric reporting.
    evidence : dict[str, object]
        Parallel evidence: the additive lower bound, the per-learned-comparator
        lower bounds, the margins, the comparator list, the method-axis caveat,
        and the integrity disclaimer.
    """

    sealed_axis: SealedAxis
    method_axis: MethodAxis
    clauses: dict[str, bool]
    evidence: dict[str, object]

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest of the canonical content of this result.

        Covers both axis values, the clauses, and a canonicalised snapshot of the
        evidence, so identical inputs produce an identical checksum.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        canonical = {
            "sealed_axis": self.sealed_axis.value,
            "method_axis": self.method_axis.value,
            "clauses": {k: self.clauses[k] for k in sorted(self.clauses)},
            "evidence": {k: _evidence_canonical(self.evidence[k]) for k in sorted(self.evidence)},
        }
        return sha256_json(canonical)

    def write(self, path: str | Path) -> None:
        """Serialise to a deterministic JSON file at *path*.

        Parameters
        ----------
        path : str or Path
            Destination file path. Parent directory must exist.
        """
        payload: dict = {
            "sealed_axis": self.sealed_axis.value,
            "method_axis": self.method_axis.value,
            "clauses": dict(self.clauses),
            "evidence": {k: _evidence_canonical(v) for k, v in self.evidence.items()},
            "checksum": self.checksum,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        Path(path).write_text(text, encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path) -> "ComposeSealedResult":
        """Deserialise a :class:`ComposeSealedResult` from a file written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Path to a JSON file produced by :meth:`write`.

        Returns
        -------
        ComposeSealedResult
            A result whose ``.checksum`` equals that of the original.

        Raises
        ------
        ComposeVerdictError
            If the file is missing required fields or carries an unknown axis value.
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ComposeVerdictError(f"Failed to read ComposeSealedResult from {path!r}: {exc}")

        try:
            sealed_axis = SealedAxis(raw["sealed_axis"])
            method_axis = MethodAxis(raw["method_axis"])
            clauses: dict[str, bool] = {k: bool(v) for k, v in raw["clauses"].items()}
            evidence: dict[str, object] = dict(raw["evidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ComposeVerdictError(f"ComposeSealedResult JSON is malformed: {exc}") from exc

        return cls(
            sealed_axis=sealed_axis,
            method_axis=method_axis,
            clauses=clauses,
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# Caveat carried in every result: METHOD_VALIDATED is not real generalization.
# ---------------------------------------------------------------------------
_METHOD_AXIS_CAVEAT: str = (
    "The method axis is reported independently of the sealed axis. "
    "METHOD_VALIDATED reflects synthetic identifiability (Phase-1 recovery) and "
    "is NOT evidence of real generalization; it neither upgrades nor is upgraded "
    "by the sealed-axis verdict."
)


def sealed_verdict(
    *,
    regime: str,
    bounds: object,
    comparators: tuple[str, ...],
    additive_margin: float,
    learned_margin: float,
    integrity: ComposeIntegrityReport,
    method_axis: MethodAxis,
) -> ComposeSealedResult:
    """Map the headline DOUBLE-UNSEEN simultaneous bounds onto the sealed-axis verdict.

    Only the double-unseen regime may enter this function; the single-unseen
    regime (or anything else) fails closed (raises). The decision uses STRICT
    inequalities at exactly the registered thresholds and reports the method axis
    and sealed axis SEPARATELY — ``method_axis`` is an input and is never
    conflated with, nor upgraded by, the sealed axis.

    Parameters
    ----------
    regime : str
        Must equal the registered double-unseen role name
        (``"sealed_double_unseen"``). Any other value raises.
    bounds : ComposeSimultaneousBounds
        Family-wise simultaneous lower bounds with a ``lower: dict[str, float]``
        mapping each comparator to its one-sided lower bound. Its key set must
        equal *comparators* exactly.
    comparators : tuple[str, ...]
        The EXACT registered comparator family
        (``config.comparator_family`` = ``additive, gears, cpa, id_only,
        l3_hypernetwork``). ``"additive"`` must be present and the learned family
        (``comparators`` minus ``{"additive"}``) must be non-empty.
    additive_margin : float
        Material margin the additive lower bound must strictly exceed
        (config ``material_margin_vs_additive`` = ``0.05``).
    learned_margin : float
        Margin every learned-comparator lower bound must strictly exceed
        (config ``learned_comparator_margin`` = ``0.0``).
    integrity : ComposeIntegrityReport
        Structural run-internal integrity self-check. When invalid, the verdict
        is ``INVALID`` regardless of the bounds.
    method_axis : MethodAxis
        The method-axis value (e.g. from Phase-1 synthetic identifiability).
        Reported as-is; never changed by this function.

    Returns
    -------
    ComposeSealedResult
        Frozen result carrying both axes, every evaluated clause, parallel
        evidence (bounds, margins, comparators, method-axis caveat, integrity
        disclaimer), and a content checksum.

    Raises
    ------
    ComposeVerdictError
        If *regime* is not the double-unseen role; if *bounds.lower* keys do not
        equal *comparators* exactly (absent OR extra); if ``"additive"`` is
        absent; or if the learned family is empty.
    """
    # ------------------------------------------------------------------
    # 1. Regime gate — only double-unseen may drive this verdict.
    # ------------------------------------------------------------------
    if regime != DOUBLE_UNSEEN_ROLE:
        raise ComposeVerdictError(
            f"sealed_verdict accepts only the double-unseen regime "
            f"{DOUBLE_UNSEEN_ROLE!r}; got {regime!r}. Single-unseen results cannot "
            "drive this verdict."
        )

    if not isinstance(method_axis, MethodAxis):
        raise ComposeVerdictError(f"method_axis must be a MethodAxis; got {method_axis!r}.")

    # ------------------------------------------------------------------
    # 2. Roster validation — EXACT registered family, no absent/extra keys.
    # ------------------------------------------------------------------
    comparator_set = set(comparators)
    if len(comparator_set) != len(comparators):
        raise ComposeVerdictError(f"comparators contains duplicates: {comparators!r}.")
    if "additive" not in comparator_set:
        raise ComposeVerdictError(
            f"'additive' must be present in the comparator roster; got {sorted(comparator_set)}."
        )

    lower = getattr(bounds, "lower", None)
    if not isinstance(lower, dict):
        raise ComposeVerdictError("bounds.lower must be a dict[str, float].")
    lower_keys = set(lower)
    if lower_keys != comparator_set:
        missing = comparator_set - lower_keys
        extra = lower_keys - comparator_set
        raise ComposeVerdictError(
            "bounds.lower keys must equal the registered comparator roster exactly "
            f"(missing={sorted(missing)}, extra={sorted(extra)})."
        )

    learned_family = tuple(c for c in comparators if c != "additive")
    if not learned_family:
        raise ComposeVerdictError(
            "learned family is empty (comparators == ('additive',)); an empty "
            "learned family is an ERROR, never a win."
        )

    # ------------------------------------------------------------------
    # 3. Evaluate EVERY clause unconditionally (full auditability).
    # ------------------------------------------------------------------
    additive_lower = float(lower["additive"])
    learned_lower = {c: float(lower[c]) for c in learned_family}

    additive_clears = additive_lower > additive_margin
    every_learned_beats = all(v > learned_margin for v in learned_lower.values())
    integrity_valid = integrity.is_valid

    clauses: dict[str, bool] = {
        "integrity_valid": integrity_valid,
        "additive_clears": additive_clears,
        "every_learned_beats": every_learned_beats,
    }

    evidence: dict[str, object] = {
        "additive_lower": additive_lower,
        "learned_lower": learned_lower,
        "additive_margin": float(additive_margin),
        "learned_margin": float(learned_margin),
        "comparators": list(comparators),
        "method_axis_caveat": _METHOD_AXIS_CAVEAT,
        "integrity_disclaimer": integrity.disclaimer,
    }

    # ------------------------------------------------------------------
    # 4. Decision — strict inequalities; integrity dominates.
    # ------------------------------------------------------------------
    if not integrity_valid:
        sealed = SealedAxis.INVALID
    elif additive_clears and every_learned_beats:
        sealed = SealedAxis.GI_LEARNABLE_WIN
    elif additive_clears and not every_learned_beats:
        sealed = SealedAxis.PARTIAL
    else:
        sealed = SealedAxis.NO_DISTINCT_WIN

    return ComposeSealedResult(
        sealed_axis=sealed,
        method_axis=method_axis,
        clauses=clauses,
        evidence=evidence,
    )
