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

_SCHEMA_VERSION = 1
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


def _validate_payload(payload: dict) -> None:
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
