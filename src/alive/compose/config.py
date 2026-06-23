"""Phase-1 config for COMPOSE-K562-v1.

A standalone, frozen config (its own YAML); deliberately does NOT extend the
CARTOGRAPHER ``alive.config.Config`` so Phase-1 work cannot perturb that run_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised for invalid Phase-1 config."""


_KNOWN = frozenset(
    {
        "k_grid",
        "lambda_grid",
        "response_dim",
        "synthetic_n_genes",
        "synthetic_rank",
        "synthetic_noise_sd",
        "min_double_unseen_pairs",
        "min_cells_per_pair",
        "calibration_fraction",
        "recovery_rel_err_tol",
        "false_gi_tol",
        "registered_seeds",
    }
)


@dataclass(frozen=True)
class ComposePhase1Config:
    """Frozen Phase-1 parameters. Load via :func:`load_compose_config`."""

    k_grid: tuple[int, ...]
    lambda_grid: tuple[float, ...]
    response_dim: int
    synthetic_n_genes: int
    synthetic_rank: int
    synthetic_noise_sd: tuple[float, ...]
    min_double_unseen_pairs: int
    min_cells_per_pair: int
    calibration_fraction: float
    recovery_rel_err_tol: float
    false_gi_tol: float
    registered_seeds: tuple[int, ...]


def load_compose_config(path: str | Path) -> ComposePhase1Config:
    """Load and validate the Phase-1 YAML config."""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
    unknown = set(raw) - _KNOWN
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")
    frac = float(raw.get("calibration_fraction", 0.6))
    if not 0.0 < frac < 1.0:
        raise ConfigError(f"calibration_fraction must be in (0,1), got {frac}")
    try:
        return ComposePhase1Config(
            k_grid=tuple(int(x) for x in raw["k_grid"]),
            lambda_grid=tuple(float(x) for x in raw["lambda_grid"]),
            response_dim=int(raw["response_dim"]),
            synthetic_n_genes=int(raw["synthetic_n_genes"]),
            synthetic_rank=int(raw["synthetic_rank"]),
            synthetic_noise_sd=tuple(float(x) for x in raw["synthetic_noise_sd"]),
            min_double_unseen_pairs=int(raw["min_double_unseen_pairs"]),
            min_cells_per_pair=int(raw["min_cells_per_pair"]),
            calibration_fraction=frac,
            recovery_rel_err_tol=float(raw["recovery_rel_err_tol"]),
            false_gi_tol=float(raw["false_gi_tol"]),
            registered_seeds=tuple(int(x) for x in raw["registered_seeds"]),
        )
    except KeyError as exc:
        raise ConfigError(f"missing required key: {exc}") from exc
