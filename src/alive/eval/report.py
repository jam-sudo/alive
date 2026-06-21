"""Two LOCKED report schemas for the CARTOGRAPHER Trust-Gate MVP (Task 17).

The report layer is a PURE READER: :func:`build_report` loads the run's persisted
artifacts and assembles one of two locked schemas chosen by the run's *terminal
state*.  It NEVER recomputes a decision or a verdict — every value it emits comes
from an artifact a prior stage already wrote to disk.

Schema selection
----------------
- ``FUTILITY_STOPPED`` futility decision AND no ``result.json`` →
  :data:`FUTILITY_KEYS` schema (``mode == "futility_stopped"``).
- ``result.json`` present (``evaluate-once`` ran) →
  :data:`CONFIRMATORY_KEYS` schema (``mode == "confirmatory"``).

The FUTILITY schema MUST NOT contain risk-coverage curves, simultaneous AURC
intervals, empirical sealed coverage, ablation results, or any negative-
performance language; it carries ``scientific_verdict: null`` and
``sealed_access_count: 0``.

"Plots"/"curves" are the underlying DATA ARRAYS serialised in JSON — no PNGs are
rendered.  A markdown rendering (``report.md``) is also written.

Public API
----------
ReportError
    Raised when required artifacts are missing or unreadable.
FUTILITY_KEYS / CONFIRMATORY_KEYS
    The exact top-level key sets of the two locked schemas.
BANNED_PHRASES
    Negative-performance substrings forbidden from any rendered report text.
build_report(run_dir)
    Load persisted artifacts and return the locked report dict; also write
    ``report.json`` and ``report.md`` next to the artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Locked top-level key sets
# ---------------------------------------------------------------------------

#: Exact top-level sections of the FUTILITY report (and ONLY these).
FUTILITY_KEYS: frozenset[str] = frozenset(
    {
        "mode",
        "config",
        "provenance",
        "flow_counts",
        "methodlock",
        "futility",
        "conformal_artifact",
        "sealed_access_count",
        "scientific_verdict",
    }
)

#: Exact top-level sections of the CONFIRMATORY report.
CONFIRMATORY_KEYS: frozenset[str] = frozenset(
    {
        "mode",
        "config",
        "provenance",
        "risk_coverage_curve",
        "simultaneous_intervals",
        "error_bound_diagnostics",
        "reliability",
        "ablations",
        "verdict_evidence",
        "sealed_access_count",
        "scientific_verdict",
    }
)

#: Negative-performance language forbidden from any rendered report text.  The
#: report is a neutral provenance document, not a verdict narrative; the
#: scientific verdict (e.g. ``NO_DISTINCT_WIN``) is carried structurally as a
#: machine value in ``scientific_verdict`` / ``verdict_evidence``, never as prose.
BANNED_PHRASES: tuple[str, ...] = (
    "worse",
    "underperform",
    "no distinct win",
    "fails to beat",
    "lost to",
    "inferior",
)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ReportError(ValueError):
    """Raised when a required artifact is missing or unreadable.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Small JSON loaders (read-only; never recompute)
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    """Load a JSON file, raising :class:`ReportError` if it is absent."""
    if not path.exists():
        raise ReportError(f"required artifact not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ReportError(f"failed to read artifact {path}: {exc}") from exc


def _config_snapshot(run_dir: Path) -> dict:
    """Read the persisted config snapshot's identifying fields (no recompute)."""
    snap = run_dir / "config.snapshot.yaml"
    if not snap.exists():
        raise ReportError(f"required artifact not found: {snap}")
    import yaml

    raw = yaml.safe_load(snap.read_text(encoding="utf-8"))
    return raw


# ---------------------------------------------------------------------------
# Section builders (each reads ONE persisted artifact)
# ---------------------------------------------------------------------------


def _config_section(run_dir: Path) -> dict:
    """Identifying config fields for the report.

    Only neutral, identifying fields are surfaced.  In particular the
    ``inference`` block is NOT echoed verbatim: its
    ``secondary_augrc_noninferiority_margin`` key contains the substring
    "inferior", and the FUTILITY report is required to be free of any
    negative-performance language even as an incidental substring.  The two
    inference scalars that matter for provenance are surfaced under neutral keys.
    """
    raw = _config_snapshot(run_dir)
    run_meta = _read_json(run_dir / "run_meta.json")
    inference = raw.get("inference") or {}
    return {
        "experiment": raw.get("experiment"),
        "run_id": run_meta.get("run_id"),
        "manifest_seed": raw.get("manifest_seed"),
        "split_fractions": raw.get("split_fractions"),
        "decision": raw.get("decision"),
        "bootstrap_replicates": inference.get("bootstrap_replicates"),
        "family_confidence": inference.get("family_confidence"),
        "futility": raw.get("futility"),
    }


def _provenance_section(run_dir: Path) -> dict:
    ledger = _read_json(run_dir / "ledger.json")
    return {
        "run_id": ledger.get("run_id"),
        "config_sha256": ledger.get("config_sha256"),
        "environment": ledger.get("environment"),
        "artifacts": ledger.get("artifacts"),
    }


def _flow_counts_section(run_dir: Path) -> dict:
    manifest = _read_json(run_dir / "manifest.json")
    counts = dict(manifest.get("counts", {}))
    return {
        "split_counts": counts,
        "fractions": manifest.get("fractions"),
    }


def _methodlock_section(run_dir: Path) -> dict:
    ml = _read_json(run_dir / "methodlock.json")
    return {
        "selected_params": ml.get("selected_params"),
        "oof_aurc": ml.get("oof_aurc"),
        "method_ids": ml.get("method_ids"),
    }


def _futility_section(run_dir: Path) -> dict:
    fd = _read_json(run_dir / "futility.json")
    return {
        "status": fd.get("status"),
        "dev_deltas": fd.get("dev_deltas"),
        "simultaneous_upper_bounds": fd.get("upper_bounds"),
        "delta_min": fd.get("delta_min"),
        "comparators": fd.get("comparators"),
        "confidence": fd.get("confidence"),
    }


def _conformal_artifact_section(run_dir: Path) -> dict:
    """Conformal artifact WITHOUT any empirical sealed coverage (futility-safe).

    Per the locked FUTILITY schema, only the shippable calibration scalars are
    surfaced: ``error_bound``, ``predict_threshold``, ``rank_k`` and ``alpha``
    (plus ``n_cal`` for context).  No empirical sealed coverage and no key whose
    name carries "coverage"/"sealed" is emitted, so a reviewer cannot mistake
    the shippable calibration artifact for a sealed-evaluation measurement.
    """
    ca = _read_json(run_dir / "conformal.json")
    return {
        "error_bound": ca.get("error_bound"),
        "predict_threshold": ca.get("predict_threshold"),
        "rank_k": ca.get("rank_k"),
        "alpha": ca.get("alpha"),
        "n_cal": ca.get("n_cal"),
    }


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def build_report(run_dir: str | Path) -> dict:
    """Assemble the LOCKED report for *run_dir*'s terminal state and write it out.

    Reads ONLY persisted artifacts; never recomputes a decision or verdict.  The
    schema is chosen from the terminal state:

    - ``result.json`` present → CONFIRMATORY schema (``mode == "confirmatory"``).
    - otherwise, ``futility.json`` status ``FUTILITY_STOPPED`` → FUTILITY schema.
    - otherwise → :class:`ReportError` (the run has no terminal state to report).

    Side effects: writes ``report.json`` (canonical) and ``report.md`` (a neutral
    markdown rendering) next to the artifacts.

    Parameters
    ----------
    run_dir : str or Path
        The per-run artifacts directory (``artifacts/cartographer/<run_id>/``).

    Returns
    -------
    dict
        The locked report dict (also serialised to ``report.json``).

    Raises
    ------
    ReportError
        If required artifacts are missing or the run has no terminal state.
    """
    run_dir = Path(run_dir)
    if not run_dir.exists():
        raise ReportError(f"run directory not found: {run_dir}")

    result_path = run_dir / "result.json"
    futility = _read_json(run_dir / "futility.json")
    status = futility.get("status")

    if result_path.exists():
        report = _build_confirmatory(run_dir)
    elif status == "FUTILITY_STOPPED":
        report = _build_futility(run_dir)
    else:
        raise ReportError(
            f"run {run_dir.name!r} has no terminal state to report: "
            "no result.json and futility status is not FUTILITY_STOPPED. "
            "Run evaluate-once (CONTINUE) or stop for futility first."
        )

    _validate_no_banned_language(report)

    (run_dir / "report.json").write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _build_futility(run_dir: Path) -> dict:
    """FUTILITY schema: shippable conformal artifact + futility decision only."""
    report = {
        "mode": "futility_stopped",
        "config": _config_section(run_dir),
        "provenance": _provenance_section(run_dir),
        "flow_counts": _flow_counts_section(run_dir),
        "methodlock": _methodlock_section(run_dir),
        "futility": _futility_section(run_dir),
        "conformal_artifact": _conformal_artifact_section(run_dir),
        "sealed_access_count": 0,
        "scientific_verdict": None,
    }
    # Enforce the LOCKED key set (defence in depth).
    if set(report.keys()) != FUTILITY_KEYS:
        raise ReportError(
            f"futility schema key drift: got {set(report.keys())!r}, expected {FUTILITY_KEYS!r}"
        )
    return report


def _build_confirmatory(run_dir: Path) -> dict:
    """CONFIRMATORY schema: assembled from result.json + result.audit.json only."""
    verdict = _read_json(run_dir / "result.json")
    audit = _read_json(run_dir / "result.audit.json")

    confirmatory = audit.get("confirmatory") or {}
    rc_curve = audit.get("risk_coverage_curve") or {"coverage": [], "selective_risk": []}
    cov_report = audit.get("coverage_report") or {}
    reliability_floors = audit.get("reliability_floors") or []

    simultaneous_intervals = {
        "aurc_point_delta": confirmatory.get("aurc_point_delta"),
        "aurc_lower_bound": confirmatory.get("aurc_lower_bound"),
        "aurc_family_passes": confirmatory.get("aurc_family_passes"),
        "augrc_degradation_upper": confirmatory.get("augrc_degradation_upper"),
        "augrc_margin": confirmatory.get("augrc_margin"),
        "augrc_no_material_degradation": confirmatory.get("augrc_no_material_degradation"),
        "family_confidence": confirmatory.get("family_confidence"),
    }
    ablations = {
        "delta_added_value": confirmatory.get("delta_added_value"),
        "delta_added_value_lower_bound": confirmatory.get("delta_added_value_lower_bound"),
        "added_value_passes": confirmatory.get("added_value_passes"),
    }
    reliability = {
        "self_distance_floors": reliability_floors,
        "self_distance_floor_min": audit.get("self_distance_floor_min"),
        "reliability_ok": bool(verdict.get("clauses", {}).get("reliability_ok")),
    }
    verdict_evidence = {
        "clauses": verdict.get("clauses"),
        "evidence": verdict.get("evidence"),
        "conformal_passes": audit.get("conformal_passes"),
        "provenance_ok": audit.get("provenance_ok"),
    }

    report = {
        "mode": "confirmatory",
        "config": _config_section(run_dir),
        "provenance": _provenance_section(run_dir),
        "risk_coverage_curve": {
            "coverage": rc_curve.get("coverage", []),
            "selective_risk": rc_curve.get("selective_risk", []),
        },
        "simultaneous_intervals": simultaneous_intervals,
        "error_bound_diagnostics": cov_report,
        "reliability": reliability,
        "ablations": ablations,
        "verdict_evidence": verdict_evidence,
        "sealed_access_count": int(audit.get("sealed_access_count", 1)),
        "scientific_verdict": verdict.get("verdict"),
    }
    if set(report.keys()) != CONFIRMATORY_KEYS:
        raise ReportError(
            f"confirmatory schema key drift: got {set(report.keys())!r}, "
            f"expected {CONFIRMATORY_KEYS!r}"
        )
    return report


# ---------------------------------------------------------------------------
# Banned-language guard + markdown rendering
# ---------------------------------------------------------------------------


def _validate_no_banned_language(report: dict) -> None:
    """Raise :class:`ReportError` if any banned negative-performance phrase appears.

    Applies only to the FUTILITY report; the confirmatory report legitimately
    carries the machine verdict value (e.g. ``NO_DISTINCT_WIN``) as a structured
    field, which is not prose and is not banned.
    """
    if report.get("mode") != "futility_stopped":
        return
    blob = json.dumps(report).lower()
    for phrase in BANNED_PHRASES:
        if phrase in blob:
            raise ReportError(
                f"futility report contains banned negative-performance phrase {phrase!r}."
            )


def _render_markdown(report: dict) -> str:
    """Render a neutral markdown view of the locked report (data arrays as JSON)."""
    mode = report["mode"]
    lines: list[str] = []
    cfg = report.get("config", {})
    lines.append(f"# CARTOGRAPHER report — {mode}")
    lines.append("")
    lines.append(f"- experiment: `{cfg.get('experiment')}`")
    lines.append(f"- run_id: `{cfg.get('run_id')}`")
    lines.append(f"- sealed_access_count: {report.get('sealed_access_count')}")
    sv = report.get("scientific_verdict")
    lines.append(f"- scientific_verdict: `{sv}`")
    lines.append("")

    if mode == "futility_stopped":
        fut = report.get("futility", {})
        lines.append("## Futility decision")
        lines.append(f"- status: `{fut.get('status')}`")
        lines.append(f"- delta_min: {fut.get('delta_min')}")
        lines.append("")
        lines.append("## Conformal artifact (shippable)")
        ca = report.get("conformal_artifact", {})
        lines.append(f"- error_bound: {ca.get('error_bound')}")
        lines.append(f"- predict_threshold: {ca.get('predict_threshold')}")
        lines.append(f"- rank_k / alpha: {ca.get('rank_k')} / {ca.get('alpha')}")
    else:
        lines.append("## Verdict evidence")
        lines.append("```json")
        lines.append(json.dumps(report.get("verdict_evidence", {}), indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
        lines.append("## Risk-coverage curve (data arrays)")
        lines.append("```json")
        lines.append(json.dumps(report.get("risk_coverage_curve", {}), indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
        lines.append("## Simultaneous intervals")
        lines.append("```json")
        lines.append(json.dumps(report.get("simultaneous_intervals", {}), indent=2, sort_keys=True))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Small helper used by the CLI when persisting dev errors (kept here so the
# report and the CLI agree on the npz key).
# ---------------------------------------------------------------------------

DEV_ERRORS_KEY: str = "errors"
DEV_IDS_KEY: str = "ids"


def load_dev_errors(run_dir: str | Path) -> tuple[tuple[str, ...], np.ndarray]:
    """Load the persisted (ids, errors) the ``develop`` stage wrote.

    Parameters
    ----------
    run_dir : str or Path
        Per-run artifacts directory.

    Returns
    -------
    tuple[tuple[str, ...], np.ndarray]
        ``(ids, errors)`` row-aligned with the MethodLock dev order.
    """
    run_dir = Path(run_dir)
    path = run_dir / "dev_errors.npz"
    if not path.exists():
        raise ReportError(f"required artifact not found: {path}")
    npz = np.load(path, allow_pickle=False)
    ids = tuple(str(x) for x in npz[DEV_IDS_KEY])
    errors = np.asarray(npz[DEV_ERRORS_KEY], dtype=np.float64)
    return ids, errors
