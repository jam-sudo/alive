"""ESM real-forward smoke-test helpers (A100 prep, spec §4.3 / §11.3 Gate C).

Pure pooling + verification logic, separated from the torch-dependent encoder so
it can be unit-tested without torch.  ``scripts/esm_smoke.py`` wires a real
:class:`~alive.data.features.Esm2Encoder` to these helpers on the A100.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def mean_pool(residue_embeddings: list[np.ndarray]) -> np.ndarray:
    """Mean-pool a list of per-residue embeddings into one vector per sequence.

    Parameters
    ----------
    residue_embeddings : list[numpy.ndarray]
        One ``(L_i, dim)`` array per sequence (BOS/EOS already stripped), matching
        :meth:`Esm2Encoder.encode_residues` output.

    Returns
    -------
    numpy.ndarray
        Shape ``(N, dim)`` — the per-sequence mean over the residue axis.

    Raises
    ------
    ValueError
        If the list is empty.
    """
    if not residue_embeddings:
        raise ValueError("mean_pool requires at least one sequence embedding.")
    return np.vstack([np.asarray(e).mean(axis=0) for e in residue_embeddings])


@dataclass(frozen=True)
class SmokeReport:
    """Outcome of an ESM forward smoke test."""

    n: int
    dim: int
    expected_dim: int
    dim_ok: bool
    all_finite: bool
    vmin: float
    vmax: float

    @property
    def ok(self) -> bool:
        """True iff the embeddings have the expected dimension and are all finite."""
        return self.dim_ok and self.all_finite


def check_pooled(pooled: np.ndarray, *, expected_dim: int) -> SmokeReport:
    """Verify pooled embeddings have the expected dimension and are finite."""
    arr = np.asarray(pooled)
    n, dim = (arr.shape[0], arr.shape[1]) if arr.ndim == 2 else (arr.shape[0], -1)
    all_finite = bool(np.isfinite(arr).all())
    return SmokeReport(
        n=int(n),
        dim=int(dim),
        expected_dim=int(expected_dim),
        dim_ok=(dim == expected_dim),
        all_finite=all_finite,
        vmin=float(np.nanmin(arr)) if arr.size else float("nan"),
        vmax=float(np.nanmax(arr)) if arr.size else float("nan"),
    )
