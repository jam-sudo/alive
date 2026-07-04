# src/alive/compose/baseline_subprocess.py
"""SYNTHETIC-ONLY: fit-role-only subprocess protocol for deep combo baselines.

No ``gears``/``cpa`` import here; the real backends run only inside pod-only
worker scripts. This module serializes a fit-role payload, invokes a worker
under a locked-env python, and returns response-space delta. See
docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md §1.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from alive.compose.baselines_combo import BaselineUnavailable, _assert_no_sealed_reference

# ``PREDICTION_REPRESENTATIONS`` is re-exported here for the Task-5 envelope /
# worker execution-manifest contract; imported now so the symbol lives in this
# module's namespace from the payload-v2 schema bump onward.
from alive.compose.fit_role import PREDICTION_REPRESENTATIONS  # noqa: F401

_SCHEMA_VERSION = 2
_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "response_dim",
        "seed",
        "allowed_roles",
        "pair_ids",
        "single_gene_ids",
        "singles_response",
        "control_mean",
        "calibration_pair_ids",
        "calibration_delta",
        "pca_components",
        "oof_folds",
        "fit_role_artifact",
        "response_projection",
    }
)

_FIT_ROLE_KEYS: frozenset[str] = frozenset(
    {
        "format",
        "artifact_schema_version",
        "path",
        "sha256",
        "content_manifest_sha256",
        "raw_data_sha256",
        "pair_manifest_sha256",
        "eligibility_hash",
        "row_identity_sha256",
        "role_obs_key",
        "perturbation_obs_key",
        "allowed_obs_roles",
        "gene_order_sha256",
        "n_cells",
        "n_genes",
        "role_counts",
        "counts_location",
    }
)
_ALLOWED_OBS_ROLES: frozenset[str] = frozenset({"control", "singles", "combo_calibration"})

_RESPONSE_PROJECTION_KEYS: frozenset[str] = frozenset(
    {
        "response_artifact_sha256",
        "raw_data_sha256",
        "gene_order_sha256",
        "hvg_gene_ids",
        "transform",
        "median_library",
        "pca_mean",
        "pca_components",
        "control_mean",
        "delta_convention",
    }
)


class PayloadError(ValueError):
    """Raised on a malformed payload / prediction file (unknown or missing key)."""


def _validate_pair_list(value: object, *, name: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise PayloadError(f"{name} must be a list")
    pairs: list[tuple[str, str]] = []
    for raw in value:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(gene, str) and gene for gene in raw)
        ):
            raise PayloadError(f"{name} entries must be two non-empty gene strings")
        pair = (raw[0], raw[1])
        if pair[0].encode("utf-8") >= pair[1].encode("utf-8"):
            raise PayloadError(f"{name} pair must be canonical and non-self: {pair!r}")
        if pair in pairs:
            raise PayloadError(f"{name} contains duplicate pair {pair!r}")
        pairs.append(pair)
    return pairs


def _is_bare_sha256(value: object) -> bool:
    """Return ``True`` for an exact bare 64-character lowercase-hex digest."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _is_file_sha256(value: object) -> bool:
    """Return ``True`` for an exact ``"sha256:" + <64 lowercase hex>`` file digest."""
    return isinstance(value, str) and value.startswith("sha256:") and _is_bare_sha256(value[7:])


def _float_hex(arr) -> list:
    """Canonical float64 ``.hex()`` list for exact cross-block float equality."""
    flat = np.asarray(arr, dtype=np.float64).ravel(order="C")
    return [float(v).hex() for v in flat]


def _float_hex_equal(a, b) -> bool:
    """Return ``True`` iff ``a`` and ``b`` are shape- and bitwise-float64-equal."""
    aa, bb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return aa.shape == bb.shape and _float_hex(aa) == _float_hex(bb)


def _validate_fit_role_block(block: object) -> None:
    """Structurally validate the ``fit_role_artifact`` payload block (spec §2.1).

    The block is checked for its exact key set, frozen format/obs-key contract,
    the exact allowed-role roster, digest formats (file vs. bare hex), and
    non-negative integer counts that sum to ``n_cells``. No file existence or
    on-disk content check happens here — the worker re-validates the ``.h5ad``
    at fit time.

    Parameters
    ----------
    block : object
        The candidate ``fit_role_artifact`` block.

    Raises
    ------
    PayloadError
        On any structural, format, digest or count violation.
    """
    if not isinstance(block, dict) or set(block) != set(_FIT_ROLE_KEYS):
        raise PayloadError("fit_role_artifact has an unexpected key set")
    if block["format"] != "anndata_h5ad" or block["counts_location"] != "X":
        raise PayloadError("fit_role_artifact format/counts_location invalid")
    if block["artifact_schema_version"] != 1:
        raise PayloadError("fit_role_artifact artifact_schema_version must be 1")
    if block["role_obs_key"] != "role" or block["perturbation_obs_key"] != "perturbation":
        raise PayloadError("fit_role_artifact obs-key contract invalid")
    roles = block["allowed_obs_roles"]
    if not isinstance(roles, list) or set(roles) != _ALLOWED_OBS_ROLES or len(roles) != 3:
        raise PayloadError("fit_role_artifact allowed_obs_roles must be the exact role roster")
    if not _is_file_sha256(block["sha256"]):
        raise PayloadError("fit_role_artifact file sha must be exact sha256:<64 lowercase hex>")
    for key in ("content_manifest_sha256", "gene_order_sha256", "row_identity_sha256"):
        if not _is_bare_sha256(block[key]):
            raise PayloadError(f"fit_role_artifact {key} must be exact 64 lowercase hex")
    for key in ("raw_data_sha256", "pair_manifest_sha256", "eligibility_hash"):
        if not isinstance(block[key], str) or not block[key]:
            raise PayloadError(f"fit_role_artifact {key} must be a non-empty string")
    if any(
        isinstance(block[k], bool) or not isinstance(block[k], int) or block[k] < 1
        for k in ("n_cells", "n_genes")
    ):
        raise PayloadError("fit_role_artifact n_cells/n_genes must be positive ints")
    counts = block["role_counts"]
    if not isinstance(counts, dict) or set(counts) != _ALLOWED_OBS_ROLES:
        raise PayloadError("fit_role_artifact role_counts must have the exact role roster")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
        raise PayloadError("fit_role_artifact role_counts must be non-negative ints")
    if sum(counts.values()) != block["n_cells"]:
        raise PayloadError("fit_role_artifact role_counts do not sum to n_cells")


def _validate_response_projection(
    block: object,
    payload: dict,
    response_dim: int,
    *,
    expected_response_artifact_sha256: str | None,
) -> None:
    """Validate the ``response_projection`` block + its cross-source equality (spec §2.2).

    Beyond the block's own key set / frozen transform / digest and shape checks,
    this enforces that the serialized operator arrays equal the top-level payload
    arrays bit-for-bit (float64 ``.hex()``), that the raw-data and gene-order
    digests equal the ``fit_role_artifact`` block's, and — when the controller
    supplies it — that ``response_artifact_sha256`` equals the independently
    verified response-artifact digest.

    Parameters
    ----------
    block : object
        The candidate ``response_projection`` block.
    payload : dict
        The full payload (for the cross-source ``pca_components`` / ``control_mean``
        and ``fit_role_artifact`` digest equality checks).
    response_dim : int
        The already-validated positive response dimension.
    expected_response_artifact_sha256 : str or None
        The independently verified combined response-artifact digest, or ``None``
        to skip that binding (supplied by the controller in a later task).

    Raises
    ------
    PayloadError
        On any structural, digest, shape, finiteness or cross-source mismatch.
    """
    if not isinstance(block, dict) or set(block) != set(_RESPONSE_PROJECTION_KEYS):
        raise PayloadError("response_projection has an unexpected key set")
    if block["transform"] != ["normalize_total_median", "log1p"]:
        raise PayloadError("response_projection transform is not the frozen transform")
    if block["delta_convention"] != "z_minus_control_mean":
        raise PayloadError("response_projection delta_convention invalid")
    if not _is_bare_sha256(block["response_artifact_sha256"]):
        raise PayloadError("response_projection response_artifact_sha256 must be 64 hex")
    if (
        expected_response_artifact_sha256 is not None
        and block["response_artifact_sha256"] != expected_response_artifact_sha256
    ):
        raise PayloadError("response_projection is not bound to the verified response artifact")
    if not _is_bare_sha256(block["gene_order_sha256"]):
        raise PayloadError("response_projection gene_order_sha256 must be 64 hex")
    hvg = block["hvg_gene_ids"]
    if (
        not isinstance(hvg, list)
        or not hvg
        or not all(isinstance(g, str) and g for g in hvg)
        or len(set(hvg)) != len(hvg)
    ):
        raise PayloadError("hvg_gene_ids must be a non-empty unique string list")
    n_hvg = len(hvg)
    pca_mean = np.asarray(block["pca_mean"], dtype=float)
    if pca_mean.shape != (n_hvg,) or not np.all(np.isfinite(pca_mean)):
        raise PayloadError("response_projection pca_mean must be a finite length-n_hvg vector")
    components = np.asarray(block["pca_components"], dtype=float)
    if components.shape != (response_dim, n_hvg) or not np.all(np.isfinite(components)):
        raise PayloadError("response_projection pca_components must be (response_dim, n_hvg)")
    control = np.asarray(block["control_mean"], dtype=float)
    if control.shape != (response_dim,) or not np.all(np.isfinite(control)):
        raise PayloadError("response_projection control_mean must be a finite response_dim vector")
    if (
        isinstance(block["median_library"], bool)
        or not isinstance(block["median_library"], (int, float))
        or not np.isfinite(block["median_library"])
        or block["median_library"] <= 0
    ):
        raise PayloadError("response_projection median_library must be a positive number")
    # cross-source equality (spec §2.2)
    if not _float_hex_equal(components, payload["pca_components"]):
        raise PayloadError("response_projection pca_components diverge from payload pca_components")
    if not _float_hex_equal(control, payload["control_mean"]):
        raise PayloadError("response_projection control_mean diverge from payload control_mean")
    fit_role = payload["fit_role_artifact"]
    if block["raw_data_sha256"] != fit_role["raw_data_sha256"]:
        raise PayloadError("response_projection raw_data_sha256 diverges from fit_role_artifact")
    if block["gene_order_sha256"] != fit_role["gene_order_sha256"]:
        raise PayloadError("response_projection gene_order_sha256 diverges from fit_role_artifact")


def _validate_payload(
    payload: dict,
    *,
    expected_response_artifact_sha256: str | None = None,
) -> None:
    if set(payload) != set(_REQUIRED_KEYS):
        raise PayloadError("payload has an unexpected key set")
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise PayloadError(f"unsupported schema_version {payload['schema_version']}")
    response_dim = payload["response_dim"]
    if isinstance(response_dim, bool) or not isinstance(response_dim, int) or response_dim < 1:
        raise PayloadError("response_dim must be a positive int")
    if isinstance(payload["seed"], bool) or not isinstance(payload["seed"], int):
        raise PayloadError("seed must be an int")
    roles = payload["allowed_roles"]
    if not isinstance(roles, list) or set(roles) != {"singles", "combo_calibration"}:
        raise PayloadError("allowed_roles must be exactly singles + combo_calibration")
    genes = payload["single_gene_ids"]
    if (
        not isinstance(genes, list)
        or not genes
        or not all(isinstance(gene, str) and gene for gene in genes)
        or len(set(genes)) != len(genes)
    ):
        raise PayloadError("single_gene_ids must be a non-empty unique string list")
    singles = np.asarray(payload["singles_response"], dtype=float)
    if singles.shape != (len(genes), response_dim) or not np.all(np.isfinite(singles)):
        raise PayloadError("singles_response must be finite and aligned to genes/response_dim")
    control = np.asarray(payload["control_mean"], dtype=float)
    if control.shape != (response_dim,) or not np.all(np.isfinite(control)):
        raise PayloadError("control_mean must be a finite response_dim vector")
    requested = _validate_pair_list(payload["pair_ids"], name="pair_ids")
    calibration = _validate_pair_list(payload["calibration_pair_ids"], name="calibration_pair_ids")
    universe = set(genes)
    if any(gene not in universe for pair in (*requested, *calibration) for gene in pair):
        raise PayloadError("all payload pair genes must exist in single_gene_ids")
    if set(requested) & set(calibration):
        raise PayloadError("pair_ids must be disjoint from calibration_pair_ids")
    calibration_delta = np.asarray(payload["calibration_delta"], dtype=float)
    if calibration_delta.shape != (len(calibration), response_dim) or not np.all(
        np.isfinite(calibration_delta)
    ):
        raise PayloadError("calibration_delta must be finite and pair/response aligned")
    components = np.asarray(payload["pca_components"], dtype=float)
    if (
        components.ndim != 2
        or components.shape[0] != response_dim
        or not np.all(np.isfinite(components))
    ):
        raise PayloadError("pca_components must be finite 2-D with response_dim rows")
    folds = payload["oof_folds"]
    if (
        not isinstance(folds, list)
        or len(folds) != len(calibration)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in folds
        )
    ):
        raise PayloadError("oof_folds must be non-negative ints aligned to calibration pairs")
    _validate_fit_role_block(payload["fit_role_artifact"])
    _validate_response_projection(
        payload["response_projection"],
        payload,
        response_dim,
        expected_response_artifact_sha256=expected_response_artifact_sha256,
    )


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_payload(work_dir: str, payload: dict) -> str:
    _validate_payload(payload)
    os.makedirs(work_dir, exist_ok=True)
    text = _canonical_json(payload)
    with open(os.path.join(work_dir, "payload.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_payload(work_dir: str) -> dict:
    with open(os.path.join(work_dir, "payload.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    _validate_payload(payload)
    return payload


def write_predictions(path: str, preds: Mapping[tuple[str, str], np.ndarray]) -> str:
    obj = {
        "schema_version": _SCHEMA_VERSION,
        "pairs": [[list(p), np.asarray(v, dtype=float).tolist()] for p, v in preds.items()],
    }
    text = _canonical_json(obj)
    with open(path + ".json", "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_predictions(path: str) -> dict[tuple[str, str], np.ndarray]:
    with open(path + ".json", encoding="utf-8") as fh:
        obj = json.load(fh)
    if set(obj) != {"schema_version", "pairs"}:
        raise PayloadError("prediction file has an unexpected key set")
    if obj.get("schema_version") != _SCHEMA_VERSION:
        raise PayloadError("prediction file has an unexpected schema_version")
    if not isinstance(obj["pairs"], list):
        raise PayloadError("prediction pairs must be a list")
    predictions: dict[tuple[str, str], np.ndarray] = {}
    for item in obj["pairs"]:
        if not isinstance(item, list) or len(item) != 2:
            raise PayloadError("each prediction record must be [pair, vector]")
        pair, vec = item
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(gene, str) and gene for gene in pair)
        ):
            raise PayloadError("prediction pair IDs must be two non-empty strings")
        pair_id = (pair[0], pair[1])
        if pair_id in predictions:
            raise PayloadError(f"duplicate prediction pair {pair_id!r}")
        predictions[pair_id] = np.asarray(vec, dtype=float)
    return predictions


@dataclass
class SubprocessBaselineBackend:
    """Guarded deep-baseline backend that runs a worker under a locked-env python.

    Implements the seam contract (``is_available`` + ``predict``) from
    ``baselines_combo.BaselineAdapter``. Imports no gears/cpa itself.
    """

    name: str
    env_python: str
    worker_script: str
    import_name: str
    seed: int = 11
    _available: bool | None = field(default=None, init=False, repr=False)
    _payload: dict | None = field(default=None, init=False, repr=False)

    def configure_payload(self, payload: Mapping[str, object]) -> None:
        """Bind a validated fit-role payload before Phase-2a prediction."""
        candidate = dict(payload)
        _assert_no_sealed_reference(candidate)
        _validate_payload(candidate)
        _canonical_json(candidate)
        self._payload = candidate

    @property
    def provenance_manifest(self) -> dict[str, object]:
        """Return the worker/payload identity bound into the Phase-2a model lock."""
        if self._payload is None:
            raise PayloadError(f"{self.name} backend has no fit-role payload assigned")
        worker = Path(self.worker_script)
        if not worker.is_file():
            raise PayloadError(f"{self.name} worker script does not exist: {str(worker)!r}")
        return {
            "name": self.name,
            "env_python": str(Path(self.env_python).resolve()),
            "worker_script": str(worker.resolve()),
            "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
            "import_name": self.import_name,
            "seed": int(self.seed),
            "payload_sha256": _sha256(_canonical_json(self._payload)),
        }

    @property
    def is_available(self) -> bool:
        if self._available is None:
            try:
                r = subprocess.run(
                    [self.env_python, "-c", f"import {self.import_name}"],
                    capture_output=True,
                    timeout=120,
                )
                self._available = r.returncode == 0
            except Exception:
                self._available = False
        return self._available

    def predict(
        self,
        context: object,
        pair_ids: list[tuple[str, str]],
        response_dim: int,
    ) -> dict[tuple[str, str], np.ndarray]:
        """Run the locked-env worker on the assigned fit-role payload.

        The fit-role ``_payload`` is assigned by the caller / Phase-2a wiring
        (never carrying a sealed role, token or path). This method scans the
        serialized payload for any sealed reference, writes it to a fresh temp
        work directory, invokes ``<env_python> <worker_script> --in <work_dir>
        --out <preds>``, and returns the parsed response-space delta.

        Parameters
        ----------
        context : object
            The frozen development-role context (validated by the adapter seam
            before this backend is touched); unused here beyond the seam guard.
        pair_ids : list of tuple of str
            The canonical pair IDs to predict.
        response_dim : int
            The required response dimension for every prediction vector.

        Returns
        -------
        dict
            Mapping from each requested canonical pair ID to a
            length-``response_dim`` prediction vector.

        Raises
        ------
        PayloadError
            If no fit-role payload has been assigned.
        ValueError
            If the serialized payload contains any sealed reference.
        BaselineUnavailable
            If the worker subprocess exits non-zero.
        """
        if self._payload is None:
            raise PayloadError(f"{self.name} backend has no fit-role payload assigned")
        payload = dict(self._payload)
        payload["pair_ids"] = [list(p) for p in pair_ids]
        payload["response_dim"] = int(response_dim)
        payload["seed"] = int(self.seed)
        _assert_no_sealed_reference(payload)  # fit-role-only guard on the payload
        with tempfile.TemporaryDirectory() as work_dir:
            write_payload(work_dir, payload)
            out = f"{work_dir}/preds"
            r = subprocess.run(
                [self.env_python, self.worker_script, "--in", work_dir, "--out", out],
                capture_output=True,
                text=True,
                timeout=1800,
            )
            if r.returncode != 0:
                raise BaselineUnavailable(f"{self.name} worker failed: {r.stderr[-500:]}")
            return read_predictions(out)
