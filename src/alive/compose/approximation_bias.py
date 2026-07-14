"""Shared integrity contracts for the COMPOSE approximation-bias evidence.

The measurement script, one-way config finalizer, scientific driver, and
registered-summary loader all consume the same evidence.  Keeping validation in
one import-light module prevents a report from being accepted at one boundary
and rejected only after the scientific seal has been consumed.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml

from alive.provenance import sha256_bytes, sha256_file, sha256_json

APPROXIMATION_BIAS_SCHEMA = "compose_approximation_bias_report_v1"
PROBE_A_SCHEMA = "compose_gears_probe_a_admission_v1"
PROTOCOL = "COMPOSE-K562-v1"
REPRESENTATION = "raw_pseudobulk_approximation"
R_STAR = 0.5
NON_FINITE = "NON_FINITE"
FAIRNESS_FLAGS = frozenset({"clear", "representation_confounded", "indeterminate"})

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TOP_KEYS = frozenset(
    {
        "schema",
        "deliverable",
        "protocol",
        "seal_status",
        "method",
        "admission_status",
        "strata",
        "gi_and_fairness",
        "provenance",
        "self_checksum",
    }
)
_GI_KEYS = frozenset(
    {
        "gi_signal_per_pair",
        "gi_signal_median",
        "floor_median",
        "bias_to_signal_ratio_R",
        "bias_to_signal_ratio_per_pair_median",
        "R_star",
        "fairness_flag",
        "bootstrap_95_interval",
        "replicates_requested",
        "replicates_finite",
        "replicates_non_finite",
    }
)
_PROVENANCE_KEYS = frozenset(
    {
        "measurement_contract_sha256",
        "basis_config_sha256",
        "git_commit",
        "norman_source_sha256",
        "fit_role_artifact_sha256",
        "response_projection_sha256",
        "gene_order_sha256",
        "pca_dim",
        "registered_seeds",
        "sealed_pair_overlap_count",
        "pod_instance",
    }
)
_STRATUM_KEYS = frozenset({"n_pairs", "per_pair", "b_distribution", "signed_pc_bias"})
_B_DISTRIBUTION_KEYS = frozenset({"median", "mean", "max", "q90"})
_BOOTSTRAP_KEYS = frozenset({"floor_median", "gi_signal_median", "bias_to_signal_ratio_R"})
_PROBE_A_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "status",
        "git_commit",
        "evidence_manifest_sha256",
        "output_bridge",
        "self_checksum",
    }
)
_OUTPUT_BRIDGE_KEYS = frozenset({"representation", "verdict", "tolerance", "max_abs_error"})


class ApproximationBiasValidationError(ValueError):
    """Raised when approximation-bias or Probe-A evidence is not trustworthy."""


def canonical_json(obj: object) -> str:
    """Return the single canonical JSON representation used by this contract."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def self_checksum(payload_without_checksum: Mapping[str, Any]) -> str:
    """Hash canonical JSON excluding the evidence object's own checksum field."""
    return sha256_bytes(canonical_json(payload_without_checksum).encode("utf-8"))


def measurement_contract_path() -> Path:
    """Return the reviewed approximation-bias design specification path."""
    return (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-07-13-compose-approximation-bias-metric-design.md"
    )


def measurement_contract_sha256() -> str:
    """Hash the exact reviewed measurement contract used by this checkout."""
    return sha256_file(measurement_contract_path())


def basis_config_sha256_from_final_config(path: str | Path, *, expected_report_sha256: str) -> str:
    """Reconstruct and hash the bias-NULL config from its one-way final form.

    Finalization is permitted to change exactly one leaf: the GEARS
    ``approximation_bias_report_sha256`` value.  Reconstructing the pre-report
    form lets every later boundary independently verify the report's
    ``basis_config_sha256`` instead of trusting finalizer history.
    """
    _hex64(expected_report_sha256, field="expected report content SHA")
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ApproximationBiasValidationError(
            f"final config is missing, unreadable, or invalid YAML: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        _fail("final config must be a YAML object")
    basis = deepcopy(dict(raw))
    try:
        gears = basis["baselines"]["gears"]
        pinned = gears["approximation_bias_report_sha256"]
    except (KeyError, TypeError) as exc:
        raise ApproximationBiasValidationError(
            "final config lacks baselines.gears.approximation_bias_report_sha256"
        ) from exc
    if pinned != expected_report_sha256:
        _fail("final config report SHA does not match the expected report content SHA")
    gears["approximation_bias_report_sha256"] = None
    return sha256_json(basis)


def _fail(message: str) -> None:
    raise ApproximationBiasValidationError(message)


def _exact_keys(value: object, expected: frozenset[str], *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    keys = set(value)
    if keys != expected:
        _fail(
            f"{field} key roster mismatch: missing={sorted(expected - keys)} "
            f"unexpected={sorted(keys - expected)}"
        )
    return value


def _hex64(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        _fail(f"{field} must be 64 lowercase hexadecimal characters")
    return value


def _git_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _GIT_COMMIT.fullmatch(value) is None:
        _fail(f"{field} must be a full 40- or 64-character lowercase hexadecimal Git commit")
    return value


def _finite(value: object, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{field} must be finite")
    if minimum is not None and number < minimum:
        _fail(f"{field} must be >= {minimum}")
    return number


def _numeric_or_sentinel(value: object, *, field: str) -> float | str:
    if value == NON_FINITE:
        return NON_FINITE
    return _finite(value, field=field)


def _interval(value: object, *, field: str) -> None:
    if value == NON_FINITE:
        return
    if not isinstance(value, list) or len(value) != 2:
        _fail(f"{field} must be [lower, upper] or {NON_FINITE!r}")
    lower = _finite(value[0], field=f"{field}[0]")
    upper = _finite(value[1], field=f"{field}[1]")
    if lower > upper:
        _fail(f"{field} lower endpoint exceeds upper endpoint")


def _validate_checksum(payload: Mapping[str, Any], *, field: str = "self_checksum") -> None:
    declared = _hex64(payload.get(field), field=field)
    body = {key: value for key, value in payload.items() if key != field}
    if declared != self_checksum(body):
        _fail(f"{field} does not match the canonical payload")


def validate_probe_a_evidence(
    evidence: Mapping[str, Any], *, expected_git_commit: str | None = None
) -> None:
    """Validate the admission-grade Probe-A bridge evidence.

    A bare ``{"status": "pass"}`` is intentionally insufficient.  Admission
    binds the protocol, Git identity, evidence-manifest digest, measured bridge
    error, preregistered tolerance, representation, and canonical checksum.
    """
    status = evidence.get("status") if isinstance(evidence, Mapping) else None
    if status != "pass":
        normalized = status if status in {"failed", "quarantined"} else "missing"
        _fail(f"Probe-A {normalized}; measurement NOT_ADMISSIBLE")
    obj = _exact_keys(evidence, _PROBE_A_KEYS, field="Probe-A evidence")
    if obj["schema"] != PROBE_A_SCHEMA:
        _fail(f"Probe-A schema must be {PROBE_A_SCHEMA!r}")
    if obj["protocol"] != PROTOCOL:
        _fail(f"Probe-A protocol must be {PROTOCOL!r}")
    commit = _git_commit(obj["git_commit"], field="Probe-A git_commit")
    if expected_git_commit is not None and commit != expected_git_commit:
        _fail("Probe-A git_commit does not match the requested measurement commit")
    _hex64(obj["evidence_manifest_sha256"], field="Probe-A evidence_manifest_sha256")
    bridge = _exact_keys(obj["output_bridge"], _OUTPUT_BRIDGE_KEYS, field="Probe-A output_bridge")
    if bridge["representation"] != REPRESENTATION:
        _fail(f"Probe-A output_bridge.representation must be {REPRESENTATION!r}")
    if bridge["verdict"] != "pass":
        _fail("Probe-A output_bridge.verdict must be 'pass'")
    tolerance = _finite(bridge["tolerance"], field="Probe-A output_bridge.tolerance", minimum=0)
    observed = _finite(
        bridge["max_abs_error"], field="Probe-A output_bridge.max_abs_error", minimum=0
    )
    if observed > tolerance:
        _fail("Probe-A output bridge exceeds its preregistered tolerance")
    _validate_checksum(obj)


def validate_approximation_bias_report(
    report: Mapping[str, Any],
    *,
    expected_protocol: str = PROTOCOL,
    expected_basis_config_sha256: str | None = None,
    expected_measurement_contract_sha256: str | None = None,
    expected_git_commit: str | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
) -> None:
    """Validate the complete v1 report, including scientific interpretation coherence."""
    obj = _exact_keys(report, _TOP_KEYS, field="approximation-bias report")
    if obj["schema"] != APPROXIMATION_BIAS_SCHEMA:
        _fail(f"report schema must be {APPROXIMATION_BIAS_SCHEMA!r}")
    if obj["deliverable"] != "gears_pseudobulk_approximation_bias_report":
        _fail("report deliverable is invalid")
    if obj["protocol"] != expected_protocol:
        _fail("report protocol does not match the scientific protocol")
    if obj["seal_status"] != "unopened":
        _fail("report seal_status must be 'unopened'")
    if obj["method"] != REPRESENTATION:
        _fail(f"report method must be {REPRESENTATION!r}")
    if obj["admission_status"] != "admitted":
        _fail("report admission_status must be 'admitted'")

    strata = _exact_keys(
        obj["strata"], frozenset({"combo_calibration", "singles"}), field="report.strata"
    )
    stratum_pair_ids: dict[str, list[str]] = {}
    signed_pc_lengths: dict[str, int] = {}
    for name in ("combo_calibration", "singles"):
        stratum = _exact_keys(strata[name], _STRATUM_KEYS, field=f"report.strata.{name}")
        n_pairs = stratum["n_pairs"]
        if isinstance(n_pairs, bool) or not isinstance(n_pairs, int) or n_pairs < 0:
            _fail(f"report.strata.{name}.n_pairs must be a non-negative int")
        per_pair = stratum["per_pair"]
        if not isinstance(per_pair, list) or len(per_pair) != n_pairs:
            _fail(f"report.strata.{name}.per_pair length must equal n_pairs")
        pair_ids: list[str] = []
        for index, entry in enumerate(per_pair):
            item = _exact_keys(
                entry,
                frozenset({"pair_id", "b_i"}),
                field=f"report.strata.{name}.per_pair[{index}]",
            )
            if not isinstance(item["pair_id"], str) or not item["pair_id"]:
                _fail(f"report.strata.{name}.per_pair[{index}].pair_id must be non-empty")
            pair_ids.append(item["pair_id"])
            value = _numeric_or_sentinel(
                item["b_i"], field=f"report.strata.{name}.per_pair[{index}].b_i"
            )
            if value != NON_FINITE and value < 0:
                _fail(f"report.strata.{name}.per_pair[{index}].b_i must be non-negative")
        if pair_ids != sorted(pair_ids) or len(set(pair_ids)) != len(pair_ids):
            _fail(f"report.strata.{name}.per_pair must have unique byte-sorted pair IDs")
        stratum_pair_ids[name] = pair_ids
        distribution = _exact_keys(
            stratum["b_distribution"],
            _B_DISTRIBUTION_KEYS,
            field=f"report.strata.{name}.b_distribution",
        )
        for key, value in distribution.items():
            metric = _numeric_or_sentinel(value, field=f"report.strata.{name}.b_distribution.{key}")
            if metric != NON_FINITE and metric < 0:
                _fail(f"report.strata.{name}.b_distribution.{key} must be non-negative")
        if not isinstance(stratum["signed_pc_bias"], list):
            _fail(f"report.strata.{name}.signed_pc_bias must be a list")
        for index, value in enumerate(stratum["signed_pc_bias"]):
            _numeric_or_sentinel(value, field=f"report.strata.{name}.signed_pc_bias[{index}]")
        signed_pc_lengths[name] = len(stratum["signed_pc_bias"])

    gi = _exact_keys(obj["gi_and_fairness"], _GI_KEYS, field="report.gi_and_fairness")
    if not isinstance(gi["gi_signal_per_pair"], list):
        _fail("report.gi_and_fairness.gi_signal_per_pair must be a list")
    gi_pair_ids: list[str] = []
    for index, entry in enumerate(gi["gi_signal_per_pair"]):
        item = _exact_keys(
            entry,
            frozenset({"pair_id", "g_i"}),
            field=f"report.gi_and_fairness.gi_signal_per_pair[{index}]",
        )
        if not isinstance(item["pair_id"], str) or not item["pair_id"]:
            _fail("GI pair IDs must be non-empty strings")
        gi_pair_ids.append(item["pair_id"])
        signal = _numeric_or_sentinel(
            item["g_i"],
            field=f"report.gi_and_fairness.gi_signal_per_pair[{index}].g_i",
        )
        if signal != NON_FINITE and signal < 0:
            _fail("GI signal magnitudes must be non-negative")
    if gi_pair_ids != stratum_pair_ids["combo_calibration"]:
        _fail("GI pair roster must exactly equal the byte-sorted combo_calibration roster")
    for field in (
        "gi_signal_median",
        "floor_median",
        "bias_to_signal_ratio_R",
        "bias_to_signal_ratio_per_pair_median",
    ):
        metric = _numeric_or_sentinel(gi[field], field=f"report.gi_and_fairness.{field}")
        if metric != NON_FINITE and metric < 0:
            _fail(f"report.gi_and_fairness.{field} must be non-negative")
    r_star = _finite(gi["R_star"], field="report.gi_and_fairness.R_star")
    if r_star != R_STAR:
        _fail(f"report.gi_and_fairness.R_star must be exactly {R_STAR}")
    ratio = gi["bias_to_signal_ratio_R"]
    expected_flag = (
        "indeterminate"
        if ratio == NON_FINITE
        else "representation_confounded"
        if float(ratio) >= R_STAR
        else "clear"
    )
    if gi["fairness_flag"] not in FAIRNESS_FLAGS or gi["fairness_flag"] != expected_flag:
        _fail("report fairness_flag is inconsistent with the registered ratio rule")
    bootstrap = _exact_keys(
        gi["bootstrap_95_interval"],
        _BOOTSTRAP_KEYS,
        field="report.gi_and_fairness.bootstrap_95_interval",
    )
    for key, value in bootstrap.items():
        _interval(value, field=f"report.gi_and_fairness.bootstrap_95_interval.{key}")
    counts: dict[str, int] = {}
    for field in ("replicates_requested", "replicates_finite", "replicates_non_finite"):
        value = gi[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _fail(f"report.gi_and_fairness.{field} must be a non-negative int")
        counts[field] = value
    if counts["replicates_requested"] <= 0:
        _fail("report.gi_and_fairness.replicates_requested must be positive")
    if (
        counts["replicates_finite"] + counts["replicates_non_finite"]
        != counts["replicates_requested"]
    ):
        _fail("report bootstrap replicate accounting does not close")

    provenance = _exact_keys(obj["provenance"], _PROVENANCE_KEYS, field="report.provenance")
    for field in (
        "measurement_contract_sha256",
        "basis_config_sha256",
        "norman_source_sha256",
        "fit_role_artifact_sha256",
        "response_projection_sha256",
        "gene_order_sha256",
    ):
        _hex64(provenance[field], field=f"report.provenance.{field}")
    if (
        expected_basis_config_sha256 is not None
        and provenance["basis_config_sha256"] != expected_basis_config_sha256
    ):
        _fail("report basis_config_sha256 does not match the bias-NULL config")
    if (
        expected_measurement_contract_sha256 is not None
        and provenance["measurement_contract_sha256"] != expected_measurement_contract_sha256
    ):
        _fail("report measurement_contract_sha256 does not match the reviewed contract")
    _git_commit(provenance["git_commit"], field="report provenance.git_commit")
    if expected_git_commit is not None and provenance["git_commit"] != expected_git_commit:
        _fail("report provenance.git_commit does not match the approved run commit")
    if not isinstance(provenance["pod_instance"], str) or not provenance["pod_instance"].strip():
        _fail("report provenance.pod_instance must be non-empty")
    if (
        isinstance(provenance["pca_dim"], bool)
        or not isinstance(provenance["pca_dim"], int)
        or provenance["pca_dim"] <= 0
    ):
        _fail("report provenance.pca_dim must be a positive int")
    for name, length in signed_pc_lengths.items():
        expected_length = provenance["pca_dim"] if stratum_pair_ids[name] else 0
        if length != expected_length:
            _fail(
                "each non-empty stratum signed_pc_bias vector length must equal "
                "provenance.pca_dim; empty strata must carry []"
            )
    seeds = provenance["registered_seeds"]
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)
    ):
        _fail("report provenance.registered_seeds must be a non-empty int list")
    if len(set(seeds)) != len(seeds):
        _fail("report provenance.registered_seeds must not contain duplicates")
    if provenance["sealed_pair_overlap_count"] != 0:
        _fail("report provenance.sealed_pair_overlap_count must be exactly zero")
    if expected_provenance is not None:
        unknown = set(expected_provenance) - _PROVENANCE_KEYS
        if unknown:
            _fail(f"unknown expected provenance field(s): {sorted(unknown)}")
        for field, expected in expected_provenance.items():
            if provenance[field] != expected:
                _fail(f"report provenance.{field} does not match the run input")
    _validate_checksum(obj)


def load_approximation_bias_report(
    path: str | Path,
    *,
    expected_content_sha256: str | None = None,
    expected_protocol: str = PROTOCOL,
    expected_basis_config_sha256: str | None = None,
    expected_measurement_contract_sha256: str | None = None,
    expected_git_commit: str | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read and fully validate a report, optionally binding its exact file bytes."""
    report_path = Path(path)
    if expected_content_sha256 is not None:
        _hex64(expected_content_sha256, field="expected report content SHA")
        if sha256_file(report_path) != expected_content_sha256:
            _fail("approximation-bias report content SHA does not match the pinned config")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApproximationBiasValidationError(
            f"approximation-bias report is missing, unreadable, or invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        _fail("approximation-bias report must be a JSON object")
    validate_approximation_bias_report(
        payload,
        expected_protocol=expected_protocol,
        expected_basis_config_sha256=expected_basis_config_sha256,
        expected_measurement_contract_sha256=expected_measurement_contract_sha256,
        expected_git_commit=expected_git_commit,
        expected_provenance=expected_provenance,
    )
    return payload
