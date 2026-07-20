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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from alive.provenance import sha256_bytes, sha256_file, sha256_json

APPROXIMATION_BIAS_SCHEMA = "compose_approximation_bias_report_v3"
PROBE_A_SCHEMA = "compose_gears_probe_a_admission_v3"
PROBE_A_REGISTRATION_SCHEMA = "compose_gears_probe_a_registration_v2"
PROBE_A_OWNER_POLICY_SCHEMA = "compose_gears_probe_a_owner_policy_v1"
PROBE_A_VERIFICATION_SCHEMA = "compose_gears_probe_a_verification_v3"
PROTOCOL = "COMPOSE-K562-v1"
REPRESENTATION = "raw_pseudobulk_approximation"
PROBE_A_REPRESENTATION = "log_normalized_pseudobulk"
PROBE_A_INPUT_TRANSFORM = "full_library_normalize_log1p_then_roster_subset"
PROBE_A_ADAPTER_TRANSFORM = "hvg_subset_center_pca_no_renormalization"
PROBE_A_NEGATIVE_OUTPUT_POLICY = "preserve_finite_signed_model_output"
PROBE_A_OWNER_POLICY_PATH = "configs/compose_gears_probe_a_owner_policy_v1.json"
PROBE_A_DETERMINISM_TOLERANCE = 0.0
PROBE_A_NUMERICAL_TOLERANCE = 1e-5
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
        "probe_a_evidence_sha256",
        "probe_a_evidence_manifest_sha256",
        "probe_a_registration_sha256",
        "probe_a_verification_sha256",
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
        "registration_sha256",
        "evidence_manifest_sha256",
        "verification_sha256",
        "output_bridge",
        "self_checksum",
    }
)
_PROBE_A_REGISTRATION_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "git_commit",
        "owner_policy_sha256",
        "input_scale",
        "determinism",
        "control_count",
        "output_bridge",
        "self_checksum",
    }
)
_PROBE_A_OWNER_POLICY_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "input_scale",
        "determinism",
        "control_count",
        "output_bridge",
        "self_checksum",
    }
)
_PROBE_A_VERIFICATION_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "status",
        "git_commit",
        "registration_sha256",
        "payload_sha256",
        "roster_receipt_sha256",
        "verifier_image_digest",
        "verifier_image_lock_sha256",
        "report_sha256",
        "evidence_manifest_sha256",
        "verifier_code_sha256",
        "output_bridge",
        "self_checksum",
    }
)
_OUTPUT_BRIDGE_KEYS = frozenset({"representation", "verdict", "tolerance", "max_abs_error"})


class ApproximationBiasValidationError(ValueError):
    """Raised when approximation-bias or Probe-A evidence is not trustworthy."""


@dataclass(frozen=True)
class ApproximationBiasEvidence:
    """Immutable, byte-bound approximation-bias evidence carried across the seal boundary.

    The scientific driver reads the file exactly once before constructing a sealed
    store.  The library entry point revalidates these immutable bytes before any
    access claim and carries only the extracted scalar fairness block afterward.
    """

    content_sha256: str
    report_bytes: bytes

    def __post_init__(self) -> None:
        if _HEX64.fullmatch(self.content_sha256) is None:
            raise ApproximationBiasValidationError(
                "ApproximationBiasEvidence.content_sha256 must be 64 lowercase hex characters"
            )
        if not isinstance(self.report_bytes, bytes):
            raise ApproximationBiasValidationError(
                "ApproximationBiasEvidence.report_bytes must be immutable bytes"
            )
        if sha256_bytes(self.report_bytes) != self.content_sha256:
            raise ApproximationBiasValidationError(
                "ApproximationBiasEvidence bytes do not match content_sha256"
            )


@dataclass(frozen=True)
class ProbeAEvidence:
    """Immutable, cross-bound Probe-A admission/registration/verification bytes."""

    content_sha256: str
    evidence_bytes: bytes
    registration_sha256: str
    registration_bytes: bytes
    verification_sha256: str
    verification_bytes: bytes

    def __post_init__(self) -> None:
        snapshots = (
            ("content_sha256", self.content_sha256, "evidence_bytes", self.evidence_bytes),
            (
                "registration_sha256",
                self.registration_sha256,
                "registration_bytes",
                self.registration_bytes,
            ),
            (
                "verification_sha256",
                self.verification_sha256,
                "verification_bytes",
                self.verification_bytes,
            ),
        )
        for sha_field, digest, bytes_field, data in snapshots:
            if _HEX64.fullmatch(digest) is None:
                raise ApproximationBiasValidationError(
                    f"ProbeAEvidence.{sha_field} must be 64 lowercase hex characters"
                )
            if not isinstance(data, bytes):
                raise ApproximationBiasValidationError(
                    f"ProbeAEvidence.{bytes_field} must be immutable bytes"
                )
            if sha256_bytes(data) != digest:
                raise ApproximationBiasValidationError(
                    f"ProbeAEvidence.{bytes_field} do not match {sha_field}"
                )


def canonical_json(obj: object) -> str:
    """Return the single canonical JSON representation used by this contract.

    ``ensure_ascii=False`` and ``allow_nan=False`` are part of the recipe: bytes
    are literal UTF-8 and no non-finite float may ever be serialised.  Every
    producer write and every consumer re-authentication routes through this so a
    file is never ``canonical`` at one boundary and rejected at another.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def canonical_file_bytes(obj: object) -> bytes:
    """The single canonical on-disk serialisation: canonical JSON + one trailing newline."""
    return (canonical_json(obj) + "\n").encode("utf-8")


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


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _linear_quantile(values: list[float], q: float) -> float:
    """Match NumPy's default linear quantile for a non-empty finite sample."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _require_derived_metric(actual: object, expected: float | str, *, field: str) -> None:
    """Require a reported aggregate to equal its per-pair-derived value."""
    if expected == NON_FINITE:
        if actual != NON_FINITE:
            _fail(f"{field} must be {NON_FINITE!r} for an empty/non-finite source roster")
        return
    observed = _finite(actual, field=field)
    if not math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-15):
        _fail(f"{field} is inconsistent with its per-pair source values")


def _validate_checksum(payload: Mapping[str, Any], *, field: str = "self_checksum") -> None:
    declared = _hex64(payload.get(field), field=field)
    body = {key: value for key, value in payload.items() if key != field}
    if declared != self_checksum(body):
        _fail(f"{field} does not match the canonical payload")


def _canonical_json_object(data: bytes, *, field: str) -> dict[str, Any]:
    """Decode one immutable snapshot and require compact canonical bytes."""
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApproximationBiasValidationError(f"{field} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        _fail(f"{field} must be a JSON object")
    try:
        expected = canonical_file_bytes(payload)
    except ValueError as exc:
        raise ApproximationBiasValidationError(f"{field} is not canonical finite JSON") from exc
    if data != expected:
        _fail(f"{field} must use canonical JSON with one trailing newline")
    return payload


def probe_a_owner_policy_path() -> Path:
    """Return the committed, outcome-independent Probe-A owner policy path."""
    return Path(__file__).resolve().parents[3] / PROBE_A_OWNER_POLICY_PATH


def validate_probe_a_owner_policy(policy: Mapping[str, Any]) -> None:
    """Validate the fixed decisions from which a run-specific registration is derived."""
    obj = _exact_keys(policy, _PROBE_A_OWNER_POLICY_KEYS, field="Probe-A owner policy")
    if obj["schema"] != PROBE_A_OWNER_POLICY_SCHEMA or obj["protocol"] != PROTOCOL:
        _fail("Probe-A owner-policy identity mismatch")
    input_scale = _exact_keys(
        obj["input_scale"], frozenset({"transform"}), field="Probe-A owner policy.input_scale"
    )
    if input_scale["transform"] != PROBE_A_INPUT_TRANSFORM:
        _fail("Probe-A owner-policy input transform is unsupported")
    determinism = _exact_keys(
        obj["determinism"],
        frozenset({"max_abs_error_tolerance"}),
        field="Probe-A owner policy.determinism",
    )
    if (
        _finite(
            determinism["max_abs_error_tolerance"],
            field="Probe-A owner policy.determinism.max_abs_error_tolerance",
            minimum=0,
        )
        != PROBE_A_DETERMINISM_TOLERANCE
    ):
        _fail("Probe-A owner-policy determinism tolerance is not the frozen exact value")
    control = _exact_keys(
        obj["control_count"],
        frozenset({"counts", "first_300_max_abs_error_tolerance"}),
        field="Probe-A owner policy.control_count",
    )
    if control["counts"] != [1, 8, 300, 301, 400]:
        _fail("Probe-A owner-policy control-count roster is unsupported")
    if (
        _finite(
            control["first_300_max_abs_error_tolerance"],
            field="Probe-A owner policy.control_count.first_300_max_abs_error_tolerance",
            minimum=0,
        )
        != PROBE_A_NUMERICAL_TOLERANCE
    ):
        _fail("Probe-A owner-policy control tolerance is not the frozen value")
    bridge = _exact_keys(
        obj["output_bridge"],
        frozenset(
            {
                "representation",
                "transform",
                "negative_output_policy",
                "max_abs_error_tolerance",
            }
        ),
        field="Probe-A owner policy.output_bridge",
    )
    if bridge["representation"] != PROBE_A_REPRESENTATION:
        _fail("Probe-A owner-policy output representation is unsupported")
    if bridge["transform"] != PROBE_A_ADAPTER_TRANSFORM:
        _fail("Probe-A owner-policy adapter transform is unsupported")
    if bridge["negative_output_policy"] != PROBE_A_NEGATIVE_OUTPUT_POLICY:
        _fail("Probe-A owner-policy negative-output policy is unsupported")
    if (
        _finite(
            bridge["max_abs_error_tolerance"],
            field="Probe-A owner policy.output_bridge.max_abs_error_tolerance",
            minimum=0,
        )
        != PROBE_A_NUMERICAL_TOLERANCE
    ):
        _fail("Probe-A owner-policy bridge tolerance is not the frozen value")
    _validate_checksum(obj)


def probe_a_owner_policy_sha256() -> str:
    """Authenticate the canonical committed owner policy and return its byte digest."""
    path = probe_a_owner_policy_path()
    if path.is_symlink() or not path.is_file():
        _fail("Probe-A owner-policy file is missing or unsafe")
    data = path.read_bytes()
    policy = _canonical_json_object(data, field="Probe-A owner policy")
    validate_probe_a_owner_policy(policy)
    return sha256_bytes(data)


def validate_probe_a_registration(
    registration: Mapping[str, Any], *, expected_git_commit: str
) -> None:
    """Validate the exact owner-frozen decisions consumed by both boundaries."""
    obj = _exact_keys(
        registration,
        _PROBE_A_REGISTRATION_KEYS,
        field="Probe-A registration",
    )
    if obj["schema"] != PROBE_A_REGISTRATION_SCHEMA or obj["protocol"] != PROTOCOL:
        _fail("Probe-A registration identity mismatch")
    if _git_commit(obj["git_commit"], field="Probe-A registration.git_commit") != _git_commit(
        expected_git_commit, field="expected Probe-A Git commit"
    ):
        _fail("Probe-A registration git_commit does not match the requested measurement commit")
    _validate_checksum(obj)
    if (
        _hex64(obj["owner_policy_sha256"], field="Probe-A registration.owner_policy_sha256")
        != probe_a_owner_policy_sha256()
    ):
        _fail("Probe-A registration owner-policy SHA-256 differs from the committed policy")
    input_scale = _exact_keys(
        obj["input_scale"],
        frozenset({"normalization_target", "transform"}),
        field="Probe-A registration.input_scale",
    )
    normalization_target = _finite(
        input_scale["normalization_target"],
        field="Probe-A registration.input_scale.normalization_target",
        minimum=0,
    )
    if normalization_target == 0:
        _fail("Probe-A registration normalization_target must be positive")
    if input_scale["transform"] != PROBE_A_INPUT_TRANSFORM:
        _fail("Probe-A registration input transform is unsupported")
    determinism = _exact_keys(
        obj["determinism"],
        frozenset({"max_abs_error_tolerance"}),
        field="Probe-A registration.determinism",
    )
    if (
        _finite(
            determinism["max_abs_error_tolerance"],
            field="Probe-A registration.determinism.max_abs_error_tolerance",
            minimum=0,
        )
        != PROBE_A_DETERMINISM_TOLERANCE
    ):
        _fail("Probe-A registration determinism tolerance differs from owner policy")
    control = _exact_keys(
        obj["control_count"],
        frozenset({"counts", "first_300_max_abs_error_tolerance"}),
        field="Probe-A registration.control_count",
    )
    if control["counts"] != [1, 8, 300, 301, 400]:
        _fail("Probe-A registration control-count roster is unsupported")
    if (
        _finite(
            control["first_300_max_abs_error_tolerance"],
            field="Probe-A registration.control_count.first_300_max_abs_error_tolerance",
            minimum=0,
        )
        != PROBE_A_NUMERICAL_TOLERANCE
    ):
        _fail("Probe-A registration control tolerance differs from owner policy")
    bridge = _exact_keys(
        obj["output_bridge"],
        frozenset(
            {
                "representation",
                "transform",
                "negative_output_policy",
                "max_abs_error_tolerance",
            }
        ),
        field="Probe-A registration.output_bridge",
    )
    if bridge["representation"] != PROBE_A_REPRESENTATION:
        _fail(f"Probe-A registration output representation must be {PROBE_A_REPRESENTATION!r}")
    if bridge["transform"] != PROBE_A_ADAPTER_TRANSFORM:
        _fail("Probe-A registration adapter transform differs from owner policy")
    if bridge["negative_output_policy"] != PROBE_A_NEGATIVE_OUTPUT_POLICY:
        _fail("Probe-A registration negative-output policy differs from owner policy")
    if (
        _finite(
            bridge["max_abs_error_tolerance"],
            field="Probe-A registration.output_bridge.max_abs_error_tolerance",
            minimum=0,
        )
        != PROBE_A_NUMERICAL_TOLERANCE
    ):
        _fail("Probe-A registration bridge tolerance differs from owner policy")


def validate_probe_a_verification(
    verification: Mapping[str, Any],
    *,
    expected_git_commit: str,
    expected_registration_sha256: str,
) -> None:
    """Validate the externally anchored offline-verifier receipt."""
    obj = _exact_keys(
        verification,
        _PROBE_A_VERIFICATION_KEYS,
        field="Probe-A verification receipt",
    )
    if obj["schema"] != PROBE_A_VERIFICATION_SCHEMA or obj["protocol"] != PROTOCOL:
        _fail("Probe-A verification receipt identity mismatch")
    if obj["status"] != "pass":
        _fail("Probe-A verification receipt status must be 'pass'")
    if _git_commit(obj["git_commit"], field="Probe-A verification.git_commit") != _git_commit(
        expected_git_commit, field="expected Probe-A Git commit"
    ):
        _fail("Probe-A verification git_commit does not match the requested measurement commit")
    if _hex64(
        obj["registration_sha256"], field="Probe-A verification.registration_sha256"
    ) != _hex64(
        expected_registration_sha256,
        field="expected Probe-A registration SHA-256",
    ):
        _fail("Probe-A verification registration SHA-256 does not match the external pin")
    for field in (
        "payload_sha256",
        "roster_receipt_sha256",
        "verifier_image_lock_sha256",
        "report_sha256",
        "evidence_manifest_sha256",
        "verifier_code_sha256",
    ):
        _hex64(obj[field], field=f"Probe-A verification.{field}")
    image_digest = obj["verifier_image_digest"]
    if (
        not isinstance(image_digest, str)
        or not image_digest.startswith("sha256:")
        or len(image_digest) != 71
    ):
        _fail("Probe-A verification.verifier_image_digest is malformed")
    _hex64(image_digest.removeprefix("sha256:"), field="Probe-A verifier image digest")
    bridge = _exact_keys(
        obj["output_bridge"],
        _OUTPUT_BRIDGE_KEYS,
        field="Probe-A verification.output_bridge",
    )
    if bridge["representation"] != PROBE_A_REPRESENTATION or bridge["verdict"] != "pass":
        _fail("Probe-A verification output bridge is not the registered candidate bridge")
    tolerance = _finite(
        bridge["tolerance"], field="Probe-A verification.output_bridge.tolerance", minimum=0
    )
    observed = _finite(
        bridge["max_abs_error"],
        field="Probe-A verification.output_bridge.max_abs_error",
        minimum=0,
    )
    if observed > tolerance:
        _fail("Probe-A verification output bridge exceeds its tolerance")
    _validate_checksum(obj)


def validate_probe_a_evidence(
    evidence: Mapping[str, Any],
    *,
    registration: Mapping[str, Any],
    registration_sha256: str,
    verification: Mapping[str, Any],
    verification_sha256: str,
    expected_git_commit: str,
) -> None:
    """Validate an admission against independently pinned source and verifier bytes."""
    status = evidence.get("status") if isinstance(evidence, Mapping) else None
    if status != "pass":
        normalized = status if status in {"failed", "quarantined"} else "missing"
        _fail(f"Probe-A {normalized}; measurement NOT_ADMISSIBLE")
    registration_pin = _hex64(registration_sha256, field="expected Probe-A registration SHA-256")
    verification_pin = _hex64(verification_sha256, field="expected Probe-A verification SHA-256")
    try:
        registration_bytes = canonical_file_bytes(registration)
        verification_bytes = canonical_file_bytes(verification)
    except (TypeError, ValueError) as exc:
        raise ApproximationBiasValidationError(
            "Probe-A registration/verification mappings are not canonical finite JSON"
        ) from exc
    if sha256_bytes(registration_bytes) != registration_pin:
        _fail("Probe-A registration mapping bytes do not match the external pin")
    if sha256_bytes(verification_bytes) != verification_pin:
        _fail("Probe-A verification mapping bytes do not match the external pin")
    validate_probe_a_registration(registration, expected_git_commit=expected_git_commit)
    validate_probe_a_verification(
        verification,
        expected_git_commit=expected_git_commit,
        expected_registration_sha256=registration_pin,
    )
    obj = _exact_keys(evidence, _PROBE_A_KEYS, field="Probe-A evidence")
    if obj["schema"] != PROBE_A_SCHEMA or obj["protocol"] != PROTOCOL:
        _fail("Probe-A admission identity mismatch")
    if _git_commit(obj["git_commit"], field="Probe-A git_commit") != _git_commit(
        expected_git_commit, field="expected Probe-A Git commit"
    ):
        _fail("Probe-A git_commit does not match the requested measurement commit")
    if _hex64(obj["registration_sha256"], field="Probe-A registration_sha256") != registration_pin:
        _fail("Probe-A registration_sha256 does not match the externally frozen pin")
    if _hex64(obj["verification_sha256"], field="Probe-A verification_sha256") != verification_pin:
        _fail("Probe-A verification_sha256 does not match the externally frozen pin")
    manifest_sha = _hex64(obj["evidence_manifest_sha256"], field="Probe-A evidence_manifest_sha256")
    if verification["evidence_manifest_sha256"] != manifest_sha:
        _fail("Probe-A admission and verification receipt manifest SHA-256 differ")
    if verification["registration_sha256"] != registration_pin:
        _fail("Probe-A admission and verification receipt registration SHA-256 differ")
    bridge = _exact_keys(obj["output_bridge"], _OUTPUT_BRIDGE_KEYS, field="Probe-A output_bridge")
    if dict(bridge) != dict(verification["output_bridge"]):
        _fail("Probe-A admission output bridge differs from the pinned verification receipt")
    registered_bridge = registration["output_bridge"]
    if bridge["representation"] != registered_bridge["representation"] or float(
        bridge["tolerance"]
    ) != float(registered_bridge["max_abs_error_tolerance"]):
        _fail("Probe-A admission output bridge differs from the pinned registration")
    if bridge["verdict"] != "pass":
        _fail("Probe-A output_bridge.verdict must be 'pass'")
    tolerance = _finite(bridge["tolerance"], field="Probe-A output_bridge.tolerance", minimum=0)
    observed = _finite(
        bridge["max_abs_error"], field="Probe-A output_bridge.max_abs_error", minimum=0
    )
    if observed > tolerance:
        _fail("Probe-A output bridge exceeds its preregistered tolerance")
    _validate_checksum(obj)


def probe_a_from_evidence(
    evidence: ProbeAEvidence,
    *,
    expected_git_commit: str | None,
    expected_registration_sha256: str,
    expected_verification_sha256: str,
) -> dict[str, Any]:
    """Revalidate all immutable Probe-A snapshots and return the admission object."""
    if not isinstance(evidence, ProbeAEvidence):
        _fail("Probe-A evidence must be a ProbeAEvidence snapshot")
    expected_registration = _hex64(
        expected_registration_sha256, field="expected Probe-A registration SHA-256"
    )
    expected_verification = _hex64(
        expected_verification_sha256, field="expected Probe-A verification SHA-256"
    )
    if evidence.registration_sha256 != expected_registration:
        _fail("Probe-A registration bytes do not match the externally frozen pin")
    if evidence.verification_sha256 != expected_verification:
        _fail("Probe-A verification bytes do not match the externally frozen pin")
    payload = _canonical_json_object(evidence.evidence_bytes, field="Probe-A admission")
    registration = _canonical_json_object(evidence.registration_bytes, field="Probe-A registration")
    verification = _canonical_json_object(
        evidence.verification_bytes, field="Probe-A verification receipt"
    )
    validation_commit = (
        expected_git_commit
        if expected_git_commit is not None
        else _git_commit(payload.get("git_commit"), field="Probe-A git_commit")
    )
    validate_probe_a_evidence(
        payload,
        registration=registration,
        registration_sha256=expected_registration,
        verification=verification,
        verification_sha256=expected_verification,
        expected_git_commit=validation_commit,
    )
    return payload


def load_probe_a_evidence(
    path: str | Path,
    *,
    registration_path: str | Path,
    verification_path: str | Path,
    expected_git_commit: str,
    expected_registration_sha256: str,
    expected_verification_sha256: str,
) -> ProbeAEvidence:
    """Read the three Probe-A artifacts once and retain their exact immutable bytes."""

    def read(path_value: str | Path, *, field: str) -> bytes:
        try:
            return Path(path_value).read_bytes()
        except OSError as exc:
            raise ApproximationBiasValidationError(
                f"{field} is missing or unreadable: {exc}"
            ) from exc

    evidence_bytes = read(path, field="Probe-A admission")
    registration_bytes = read(registration_path, field="Probe-A registration")
    verification_bytes = read(verification_path, field="Probe-A verification receipt")
    evidence = ProbeAEvidence(
        content_sha256=sha256_bytes(evidence_bytes),
        evidence_bytes=evidence_bytes,
        registration_sha256=sha256_bytes(registration_bytes),
        registration_bytes=registration_bytes,
        verification_sha256=sha256_bytes(verification_bytes),
        verification_bytes=verification_bytes,
    )
    probe_a_from_evidence(
        evidence,
        expected_git_commit=expected_git_commit,
        expected_registration_sha256=expected_registration_sha256,
        expected_verification_sha256=expected_verification_sha256,
    )
    return evidence


def validate_approximation_bias_report(
    report: Mapping[str, Any],
    *,
    expected_protocol: str = PROTOCOL,
    expected_basis_config_sha256: str | None = None,
    expected_measurement_contract_sha256: str | None = None,
    expected_git_commit: str | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
) -> None:
    """Validate the complete v3 report, including scientific interpretation coherence."""
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
    stratum_bias_values: dict[str, dict[str, float | str]] = {}
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
        bias_by_pair: dict[str, float | str] = {}
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
            bias_by_pair[item["pair_id"]] = value
        if pair_ids != sorted(pair_ids) or len(set(pair_ids)) != len(pair_ids):
            _fail(f"report.strata.{name}.per_pair must have unique byte-sorted pair IDs")
        stratum_pair_ids[name] = pair_ids
        stratum_bias_values[name] = bias_by_pair
        distribution = _exact_keys(
            stratum["b_distribution"],
            _B_DISTRIBUTION_KEYS,
            field=f"report.strata.{name}.b_distribution",
        )
        for key, value in distribution.items():
            metric = _numeric_or_sentinel(value, field=f"report.strata.{name}.b_distribution.{key}")
            if metric != NON_FINITE and metric < 0:
                _fail(f"report.strata.{name}.b_distribution.{key} must be non-negative")
        finite_bias = [value for value in bias_by_pair.values() if value != NON_FINITE]
        expected_distribution: dict[str, float | str]
        if finite_bias:
            expected_distribution = {
                "median": _median(finite_bias),
                "mean": math.fsum(finite_bias) / len(finite_bias),
                "max": max(finite_bias),
                "q90": _linear_quantile(finite_bias, 0.9),
            }
        else:
            expected_distribution = dict.fromkeys(_B_DISTRIBUTION_KEYS, NON_FINITE)
        for key, expected in expected_distribution.items():
            _require_derived_metric(
                distribution[key], expected, field=f"report.strata.{name}.b_distribution.{key}"
            )
        if not isinstance(stratum["signed_pc_bias"], list):
            _fail(f"report.strata.{name}.signed_pc_bias must be a list")
        for index, value in enumerate(stratum["signed_pc_bias"]):
            _numeric_or_sentinel(value, field=f"report.strata.{name}.signed_pc_bias[{index}]")
        signed_pc_lengths[name] = len(stratum["signed_pc_bias"])

    gi = _exact_keys(obj["gi_and_fairness"], _GI_KEYS, field="report.gi_and_fairness")
    if not isinstance(gi["gi_signal_per_pair"], list):
        _fail("report.gi_and_fairness.gi_signal_per_pair must be a list")
    gi_pair_ids: list[str] = []
    gi_by_pair: dict[str, float | str] = {}
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
        gi_by_pair[item["pair_id"]] = signal
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

    combo_bias = stratum_bias_values["combo_calibration"]
    finite_floor = [value for value in combo_bias.values() if value != NON_FINITE]
    finite_gi = [value for value in gi_by_pair.values() if value != NON_FINITE]
    expected_floor: float | str = _median(finite_floor) if finite_floor else NON_FINITE
    expected_gi: float | str = _median(finite_gi) if finite_gi else NON_FINITE
    _require_derived_metric(
        gi["floor_median"], expected_floor, field="report.gi_and_fairness.floor_median"
    )
    _require_derived_metric(
        gi["gi_signal_median"], expected_gi, field="report.gi_and_fairness.gi_signal_median"
    )
    expected_ratio: float | str = (
        expected_floor / expected_gi
        if expected_floor != NON_FINITE and expected_gi != NON_FINITE and expected_gi != 0.0
        else NON_FINITE
    )
    _require_derived_metric(
        gi["bias_to_signal_ratio_R"],
        expected_ratio,
        field="report.gi_and_fairness.bias_to_signal_ratio_R",
    )
    pair_ratios = [
        combo_bias[pair_id] / gi_by_pair[pair_id]
        for pair_id in gi_pair_ids
        if combo_bias[pair_id] != NON_FINITE
        and gi_by_pair[pair_id] != NON_FINITE
        and gi_by_pair[pair_id] != 0.0
    ]
    expected_pair_ratio: float | str = _median(pair_ratios) if pair_ratios else NON_FINITE
    _require_derived_metric(
        gi["bias_to_signal_ratio_per_pair_median"],
        expected_pair_ratio,
        field="report.gi_and_fairness.bias_to_signal_ratio_per_pair_median",
    )
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
    interval_values = list(bootstrap.values())
    if counts["replicates_finite"] == 0 and any(value != NON_FINITE for value in interval_values):
        _fail("report bootstrap intervals must all be NON_FINITE when no replicate is finite")
    if counts["replicates_finite"] > 0 and any(value == NON_FINITE for value in interval_values):
        _fail("report bootstrap intervals must all be finite when finite replicates exist")

    provenance = _exact_keys(obj["provenance"], _PROVENANCE_KEYS, field="report.provenance")
    for field in (
        "measurement_contract_sha256",
        "basis_config_sha256",
        "norman_source_sha256",
        "fit_role_artifact_sha256",
        "response_projection_sha256",
        "gene_order_sha256",
        "probe_a_evidence_sha256",
        "probe_a_evidence_manifest_sha256",
        "probe_a_registration_sha256",
        "probe_a_verification_sha256",
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


def report_from_evidence(
    evidence: ApproximationBiasEvidence,
    *,
    expected_content_sha256: str | None = None,
    expected_protocol: str = PROTOCOL,
    expected_basis_config_sha256: str | None = None,
    expected_measurement_contract_sha256: str | None = None,
    expected_git_commit: str | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate an immutable evidence snapshot and return a fresh report object."""
    if not isinstance(evidence, ApproximationBiasEvidence):
        _fail("approximation-bias evidence must be an ApproximationBiasEvidence snapshot")
    actual_sha = sha256_bytes(evidence.report_bytes)
    if actual_sha != evidence.content_sha256:
        _fail("approximation-bias evidence bytes changed after capture")
    if expected_content_sha256 is not None:
        _hex64(expected_content_sha256, field="expected report content SHA")
        if actual_sha != expected_content_sha256:
            _fail("approximation-bias report content SHA does not match the pinned config")
    try:
        payload = json.loads(evidence.report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApproximationBiasValidationError(
            f"approximation-bias evidence is invalid JSON: {exc}"
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


def load_approximation_bias_report(
    path: str | Path,
    *,
    expected_content_sha256: str | None = None,
    expected_protocol: str = PROTOCOL,
    expected_basis_config_sha256: str | None = None,
    expected_measurement_contract_sha256: str | None = None,
    expected_git_commit: str | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
) -> ApproximationBiasEvidence:
    """Read a report once and return fully validated immutable evidence bytes."""
    report_path = Path(path)
    try:
        report_bytes = report_path.read_bytes()
    except OSError as exc:
        raise ApproximationBiasValidationError(
            f"approximation-bias report is missing or unreadable: {exc}"
        ) from exc
    evidence = ApproximationBiasEvidence(
        content_sha256=sha256_bytes(report_bytes), report_bytes=report_bytes
    )
    report_from_evidence(
        evidence,
        expected_content_sha256=expected_content_sha256,
        expected_protocol=expected_protocol,
        expected_basis_config_sha256=expected_basis_config_sha256,
        expected_measurement_contract_sha256=expected_measurement_contract_sha256,
        expected_git_commit=expected_git_commit,
        expected_provenance=expected_provenance,
    )
    return evidence
