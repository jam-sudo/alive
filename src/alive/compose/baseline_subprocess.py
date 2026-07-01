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
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

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


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_payload(work_dir: str, payload: dict) -> str:
    keys = set(payload)
    if keys != set(_REQUIRED_KEYS):
        raise PayloadError(f"payload keys {sorted(keys)} != required {sorted(_REQUIRED_KEYS)}")
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise PayloadError(f"unsupported schema_version {payload['schema_version']}")
    os.makedirs(work_dir, exist_ok=True)
    text = _canonical_json(payload)
    with open(os.path.join(work_dir, "payload.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_payload(work_dir: str) -> dict:
    with open(os.path.join(work_dir, "payload.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    if set(payload) != set(_REQUIRED_KEYS):
        raise PayloadError("payload on disk has an unexpected key set")
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
    if obj.get("schema_version") != _SCHEMA_VERSION:
        raise PayloadError("prediction file has an unexpected schema_version")
    return {tuple(pair): np.asarray(vec, dtype=float) for pair, vec in obj["pairs"]}


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
