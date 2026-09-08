"""The four SYMMETRIC composition models for COMPOSE-K562-v1 Phase 2a (§2.3).

Genetic-combination prediction is **unordered**: a perturbation pair ``(g, h)``
is the same intervention as ``(h, g)``. Every model in this module therefore
satisfies the load-bearing invariant

    ``predict_eps(Z, g, h) == predict_eps(Z, h, g)``   (exactly).

The four models form the registered ablation ladder plus the non-bilinear
ID-only comparator (config ``compose_k562_v1_phase2.yaml`` §method/baselines):

* :class:`L1Model` — the symmetric, identifiable bilinear operator. It reuses the
  Phase-1 identification machinery (:func:`alive.compose.identify.identify_operator`,
  :func:`alive.compose.operator.bilinear_predict`), which is symmetric by
  construction because the pair feature is built from the *symmetrised* outer
  product.
* :class:`L2Model` — a preregistered, per-output monotone saturation of the L1
  score, ``scale_m * tanh(L1_score_m)``, with each ``scale_m`` fitted by a
  closed-form 1-D least-squares regression of the calibration target onto
  ``tanh(L1_score_m)``. Monotone + sign-preserving + bounded, hence still
  symmetric.
* :class:`IDOnlyModel` — ridge regression on the **symmetric** non-bilinear pair
  features ``[z_g + z_h, |z_g - z_h|]``. Concatenating ``[z_g, z_h]`` is
  PROHIBITED (order-dependent); only symmetric combinations are used.
* :class:`L3Model` — a higher-capacity symmetric learner: a small, fully
  deterministic numpy MLP on the same symmetric pair features. Initialisation and
  training are seeded and reproducible, so two fits on identical data are
  byte-identical.

All models share the typed protocol :class:`SymmetricModel`:

    ``fit(Z, pairs, eps_obs, *, lam) -> Self``
    ``predict_eps(Z, g, h) -> np.ndarray``  (length ``p`` = ``eps_obs.shape[1]``)

These are development-stage methods only. No sealed outcome enters this module;
``eps_obs`` is always a development-role calibration target.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from alive.compose.identify import (
    EstimatorInputError,
    SingularDesignError,
    identify_operator,
    solve_ridge_svd,
)
from alive.compose.operator import bilinear_predict
from alive.provenance import sha256_json

# Deterministic seed for the L3 numpy MLP (init + training are reproducible).
_L3_SEED = 20260624


@runtime_checkable
class SymmetricModel(Protocol):
    """Typed protocol shared by every symmetric composition model.

    A conforming model fits a development-role calibration target and predicts an
    order-invariant genetic-interaction (GI) vector for any gene pair.
    """

    def fit(
        self,
        Z: np.ndarray,
        pairs: list[tuple[int, int]],
        eps_obs: np.ndarray,
        *,
        lam: float,
    ) -> "SymmetricModel":
        """Fit on calibration pairs; return ``self`` for chaining."""
        ...

    def predict_eps(self, Z: np.ndarray, g: int, h: int) -> np.ndarray:
        """Predict the length-``p`` GI vector for pair ``(g, h)`` (symmetric)."""
        ...


def _check_indices(Z: np.ndarray, g: int, h: int) -> None:
    """Raise ``IndexError`` if either gene index is out of range for ``Z``."""
    n = Z.shape[0]
    if not (0 <= g < n) or not (0 <= h < n):
        raise IndexError(f"gene index out of range: g={g}, h={h}, n_genes={n}")


def _sym_id_feature(z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray:
    """Symmetric non-bilinear pair feature ``[z_g + z_h, |z_g - z_h|]``.

    Both blocks are invariant to swapping ``z_g`` and ``z_h`` (the sum is
    symmetric; the absolute difference is even), so the resulting feature — and
    any function of it — is order-invariant. Concatenating ``[z_g, z_h]`` is
    deliberately NOT used because it would depend on label order (plan §2.3).
    """
    z_g = np.asarray(z_g, dtype=np.float64)
    z_h = np.asarray(z_h, dtype=np.float64)
    return np.concatenate([z_g + z_h, np.abs(z_g - z_h)])


# --------------------------------------------------------------------------- #
# L1 — symmetric identifiable bilinear operator
# --------------------------------------------------------------------------- #
class L1Model:
    """Symmetric, identifiable bilinear operator (headline ablation, §3.2).

    ``eps_gh[m] = z_g^T B_m z_h`` with each ``B_m`` symmetric. The operator is
    estimated by (ridge) least squares via
    :func:`alive.compose.identify.identify_operator`; prediction reuses
    :func:`alive.compose.operator.bilinear_predict`, which is symmetric because
    its pair feature uses the symmetrised outer product.

    Attributes
    ----------
    coef_
        Operator coefficient matrix of shape ``(p, sym_dim)`` after :meth:`fit`.
    """

    def __init__(self) -> None:
        self.coef_: np.ndarray | None = None

    def fit(
        self,
        Z: np.ndarray,
        pairs: list[tuple[int, int]],
        eps_obs: np.ndarray,
        *,
        lam: float,
    ) -> "L1Model":
        """Estimate the bilinear operator by ridge least squares.

        Parameters
        ----------
        Z
            Per-gene factor matrix of shape ``(n_genes, k)``.
        pairs
            Calibration gene pairs (canonical or not; the bilinear feature is
            symmetric so order is irrelevant).
        eps_obs
            Calibration GI targets of shape ``(n_pairs, p)``.
        lam
            Ridge penalty (``0.0`` for the noiseless algebraic fit).
        """
        self.coef_ = identify_operator(Z, pairs, eps_obs, lam=lam)
        return self

    def predict_eps(self, Z: np.ndarray, g: int, h: int) -> np.ndarray:
        """Predict the GI vector ``coef_ @ pair_feature(z_g, z_h)`` (symmetric)."""
        if self.coef_ is None:
            raise RuntimeError("L1Model.predict_eps called before fit")
        Z = np.asarray(Z, dtype=np.float64)
        _check_indices(Z, g, h)
        return np.asarray(bilinear_predict(self.coef_, Z[g], Z[h]), dtype=np.float64)


# --------------------------------------------------------------------------- #
# L2 — preregistered monotone saturation of the L1 score
# --------------------------------------------------------------------------- #
class L2Model:
    """Per-output monotone saturation ``scale_m * tanh(L1_score_m)`` (§ladder).

    The saturating nonlinearity is preregistered (``tanh``); the only free
    parameter is a per-output scale ``scale_m``, fitted by closed-form 1-D least
    squares of the calibration target onto ``tanh(L1_score_m)``. Because ``tanh``
    is monotone and odd and the L1 score is symmetric, the L2 prediction is
    monotone in the L1 score, sign-preserving (for ``scale_m >= 0``) and bounded
    by ``|scale_m|`` — and remains symmetric in ``(g, h)``.

    Attributes
    ----------
    l1_
        The underlying fitted :class:`L1Model`.
    scale_
        Per-output saturation scales of shape ``(p,)``.
    """

    def __init__(self) -> None:
        self.l1_ = L1Model()
        self.scale_: np.ndarray | None = None

    def fit(
        self,
        Z: np.ndarray,
        pairs: list[tuple[int, int]],
        eps_obs: np.ndarray,
        *,
        lam: float,
    ) -> "L2Model":
        """Fit the L1 operator, then a per-output ``tanh`` saturation scale."""
        Z = np.asarray(Z, dtype=np.float64)
        eps_obs = np.asarray(eps_obs, dtype=np.float64)
        self.l1_.fit(Z, pairs, eps_obs, lam=lam)
        # L1 score on every calibration pair: shape (n_pairs, p).
        scores = np.vstack([self.l1_.predict_eps(Z, g, h) for g, h in pairs])
        sat = np.tanh(scores)  # saturated basis, shape (n_pairs, p)
        # Closed-form 1-D LS per output coordinate: scale_m = <sat_m, y_m> / <sat_m, sat_m>.
        num = np.sum(sat * eps_obs, axis=0)
        den = np.sum(sat * sat, axis=0)
        unconstrained = np.where(den > 1e-12, num / np.maximum(den, 1e-12), 0.0)
        # Enforce the registered non-decreasing, sign-preserving saturation.
        self.scale_ = np.maximum(unconstrained, 0.0)
        return self

    def predict_eps(self, Z: np.ndarray, g: int, h: int) -> np.ndarray:
        """Predict ``scale_ * tanh(L1_score)`` (monotone, bounded, symmetric)."""
        if self.scale_ is None:
            raise RuntimeError("L2Model.predict_eps called before fit")
        score = self.l1_.predict_eps(Z, g, h)
        return np.asarray(self.scale_ * np.tanh(score), dtype=np.float64)


# --------------------------------------------------------------------------- #
# ID-only — ridge on symmetric non-bilinear features
# --------------------------------------------------------------------------- #
class IDOnlyModel:
    """Ridge on the symmetric non-bilinear pair feature — the STRUCTURE comparator (§baselines).

    Registered role: it isolates the contribution of the *bilinear structure* by giving a
    non-bilinear model the SAME factor bank (ESM columns included). It is deliberately NOT a
    biological-prior ID-null: an encoder ablation needs an arm without the ESM columns, which is
    not registered (decision D2, 2026-09-07). No claim about ESM added value rests on this arm.

    The feature is ``[z_g + z_h, |z_g - z_h|]`` plus an intercept; both blocks are
    order-invariant, so the model is symmetric.

    Attributes
    ----------
    weight_
        Ridge coefficient matrix of shape ``(feature_dim + 1, p)`` (last row is
        the intercept) after :meth:`fit`.
    """

    def __init__(self) -> None:
        self.weight_: np.ndarray | None = None

    @staticmethod
    def _design(Z: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
        """Symmetric design matrix with an intercept column, shape ``(n, d+1)``."""
        feats = np.vstack([_sym_id_feature(Z[g], Z[h]) for g, h in pairs])
        ones = np.ones((feats.shape[0], 1))
        return np.hstack([feats, ones])

    def fit(
        self,
        Z: np.ndarray,
        pairs: list[tuple[int, int]],
        eps_obs: np.ndarray,
        *,
        lam: float,
    ) -> "IDOnlyModel":
        """Ridge-fit ``eps_obs`` on the symmetric pair feature (intercept unpenalised)."""
        Z = np.asarray(Z, dtype=np.float64)
        eps_obs = np.asarray(eps_obs, dtype=np.float64)
        lam = float(lam)
        if not np.isfinite(lam) or lam < 0.0:
            raise EstimatorInputError(f"lam must be finite and non-negative, got {lam!r}")
        if eps_obs.ndim == 1:
            eps_obs = eps_obs[:, np.newaxis]
        if not np.all(np.isfinite(Z)) or not np.all(np.isfinite(eps_obs)):
            raise EstimatorInputError("ID-only factors and targets must contain only finite values")
        phi = self._design(Z, pairs)  # (n, d+1)
        d1 = phi.shape[1]
        if eps_obs.ndim != 2 or eps_obs.shape[0] != phi.shape[0]:
            raise EstimatorInputError("ID-only targets must be row-aligned with the pair roster")

        if lam == 0.0:
            # Preserve the preregistered full-rank requirement for this comparator,
            # but compute its unique solution without squaring the condition number.
            rcond = float(max(phi.shape) * np.finfo(np.float64).eps)
            try:
                weight, _, rank, _ = np.linalg.lstsq(phi, eps_obs, rcond=rcond)
            except np.linalg.LinAlgError as exc:
                raise SingularDesignError(
                    f"id_only unregularized solver failed at lam={lam!r}: {exc}"
                ) from exc
            if int(rank) < d1:
                raise SingularDesignError(
                    f"id_only design has no unique ridge solution at lam={lam!r}: "
                    f"rank={rank} < feature_dim={d1}"
                )
            self.weight_ = np.asarray(weight, dtype=np.float64)
            return self

        # Eliminating the unpenalised intercept by centering reduces the problem
        # exactly to ridge on the feature columns.  The shared SVD filter-factor
        # solver then applies lambda without ever forming a Gram matrix.
        features = phi[:, :-1]
        feature_mean = np.mean(features, axis=0)
        target_mean = np.mean(eps_obs, axis=0)
        slopes = solve_ridge_svd(
            features - feature_mean,
            eps_obs - target_mean,
            lam=lam,
        )
        intercept = target_mean - feature_mean @ slopes
        self.weight_ = np.vstack([slopes, intercept])
        if not np.all(np.isfinite(self.weight_)):
            raise SingularDesignError(
                f"id_only regularized solver produced non-finite weights at lam={lam!r}"
            )
        return self

    def predict_eps(self, Z: np.ndarray, g: int, h: int) -> np.ndarray:
        """Predict from the symmetric pair feature (order-invariant)."""
        if self.weight_ is None:
            raise RuntimeError("IDOnlyModel.predict_eps called before fit")
        Z = np.asarray(Z, dtype=np.float64)
        _check_indices(Z, g, h)
        feat = np.append(_sym_id_feature(Z[g], Z[h]), 1.0)  # intercept
        return np.asarray(feat @ self.weight_, dtype=np.float64)


# --------------------------------------------------------------------------- #
# L3 — higher-capacity symmetric numpy MLP
# --------------------------------------------------------------------------- #
class L3Model:
    """Deterministic symmetric MLP on the symmetric pair feature (§ladder).

    A small two-hidden-layer ``tanh`` MLP mapping ``[z_g + z_h, |z_g - z_h|]`` to
    the GI vector. Because the input feature is order-invariant, the network is
    symmetric for any weights. Initialisation (seeded Glorot-style) and training
    (full-batch gradient descent with a fixed schedule, seeded) are fully
    deterministic, so two fits on identical data produce byte-identical
    parameters and predictions.

    Attributes
    ----------
    weights_
        Tuple of weight/bias arrays after :meth:`fit`.
    """

    _HIDDEN = (16, 16)
    _N_STEPS = 400
    _LR = 0.05

    def __init__(self) -> None:
        self.weights_: tuple[np.ndarray, ...] | None = None
        self._dims: tuple[int, ...] | None = None

    # -- architecture -------------------------------------------------------- #
    def _lazy_init(self, Z: np.ndarray, pairs: list[tuple[int, int]], eps_obs: np.ndarray) -> None:
        """Deterministically initialise weights from the first feature/target shapes."""
        Z = np.asarray(Z, dtype=np.float64)
        eps_obs = np.asarray(eps_obs, dtype=np.float64)
        in_dim = _sym_id_feature(Z[pairs[0][0]], Z[pairs[0][1]]).shape[0]
        out_dim = eps_obs.shape[1]
        dims = (in_dim, *self._HIDDEN, out_dim)
        self._dims = dims
        rng = np.random.default_rng(_L3_SEED)
        w: list[np.ndarray] = []
        for d_in, d_out in zip(dims[:-1], dims[1:]):
            scale = np.sqrt(2.0 / (d_in + d_out))  # deterministic Glorot init
            w.append(rng.normal(scale=scale, size=(d_in, d_out)))  # weight
            w.append(np.zeros(d_out))  # bias
        self.weights_ = tuple(w)

    def _forward_batch(self, feats: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
        """Forward pass over a feature batch; return output and per-layer activations."""
        assert self.weights_ is not None
        acts = [feats]
        a = feats
        n_layers = len(self.weights_) // 2
        for i in range(n_layers):
            wi = self.weights_[2 * i]
            bi = self.weights_[2 * i + 1]
            z = a @ wi + bi
            a = np.tanh(z) if i < n_layers - 1 else z  # linear output layer
            acts.append(a)
        return a, acts

    def _forward(self, Z: np.ndarray, g: int, h: int) -> np.ndarray:
        """Forward pass for a single pair (used by tests for the init-only error)."""
        Z = np.asarray(Z, dtype=np.float64)
        feat = _sym_id_feature(Z[g], Z[h])[None, :]
        out, _ = self._forward_batch(feat)
        return out[0]

    # -- training ------------------------------------------------------------ #
    def fit(
        self,
        Z: np.ndarray,
        pairs: list[tuple[int, int]],
        eps_obs: np.ndarray,
        *,
        lam: float,
    ) -> "L3Model":
        """Deterministically initialise and train the MLP by full-batch GD.

        Uses a fixed step count, learning rate and L2 weight decay (``lam``) so
        the optimisation trajectory — and therefore the final parameters — is a
        deterministic function of the data and the module seed.
        """
        Z = np.asarray(Z, dtype=np.float64)
        eps_obs = np.asarray(eps_obs, dtype=np.float64)
        self._lazy_init(Z, pairs, eps_obs)
        assert self.weights_ is not None

        feats = np.vstack([_sym_id_feature(Z[g], Z[h]) for g, h in pairs])
        y = eps_obs
        n = feats.shape[0]
        n_layers = len(self.weights_) // 2
        weights = list(self.weights_)

        for _ in range(self._N_STEPS):
            # Forward pass, caching each layer's activation. The hidden layers use
            # tanh, so their derivative is 1 - a^2 from the activation alone.
            acts = [feats]
            a = feats
            for i in range(n_layers):
                z = a @ weights[2 * i] + weights[2 * i + 1]
                a = np.tanh(z) if i < n_layers - 1 else z
                acts.append(a)
            pred = acts[-1]

            # Backprop the MSE gradient (factor 2/n included).
            grad = (2.0 / n) * (pred - y)  # dL/d(output pre-activation), linear head
            for i in reversed(range(n_layers)):
                a_in = acts[i]  # input activation to layer i
                gw = a_in.T @ grad + lam * weights[2 * i]  # + L2 weight decay
                gb = grad.sum(axis=0)
                if i > 0:
                    # Propagate into the previous (tanh) layer: tanh'(acts[i]) = 1 - acts[i]^2.
                    grad = (grad @ weights[2 * i].T) * (1.0 - acts[i] ** 2)
                weights[2 * i] = weights[2 * i] - self._LR * gw
                weights[2 * i + 1] = weights[2 * i + 1] - self._LR * gb

        self.weights_ = tuple(weights)
        return self

    def predict_eps(self, Z: np.ndarray, g: int, h: int) -> np.ndarray:
        """Predict the GI vector for ``(g, h)`` (order-invariant by feature)."""
        if self.weights_ is None:
            raise RuntimeError("L3Model.predict_eps called before fit")
        Z = np.asarray(Z, dtype=np.float64)
        _check_indices(Z, g, h)
        return np.asarray(self._forward(Z, g, h), dtype=np.float64)


def _array_state(value: np.ndarray) -> dict:
    """Return a lossless canonical representation of a fitted numeric array."""
    array = np.asarray(value)
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "float64_hex": [float(item).hex() for item in array.astype(np.float64).ravel(order="C")],
    }


def fitted_model_artifact(model: SymmetricModel) -> dict:
    """Return the canonical fitted-state artifact for a built-in COMPOSE model.

    Arbitrary duck-typed objects are rejected: a scientific method cannot gain a
    trusted checksum merely by using a registered roster name.
    """
    if isinstance(model, L1Model):
        if model.coef_ is None:
            raise EstimatorInputError("cannot serialize an unfitted L1Model")
        state = {"coef": _array_state(model.coef_)}
    elif isinstance(model, L2Model):
        if model.l1_.coef_ is None or model.scale_ is None:
            raise EstimatorInputError("cannot serialize an unfitted L2Model")
        state = {
            "l1_coef": _array_state(model.l1_.coef_),
            "scale": _array_state(model.scale_),
        }
    elif isinstance(model, IDOnlyModel):
        if model.weight_ is None:
            raise EstimatorInputError("cannot serialize an unfitted IDOnlyModel")
        state = {"weight": _array_state(model.weight_)}
    elif isinstance(model, L3Model):
        if model.weights_ is None or model._dims is None:
            raise EstimatorInputError("cannot serialize an unfitted L3Model")
        state = {
            "dims": list(model._dims),
            "hidden": list(model._HIDDEN),
            "n_steps": model._N_STEPS,
            "learning_rate": float(model._LR).hex(),
            "seed": _L3_SEED,
            "weights": [_array_state(value) for value in model.weights_],
        }
    else:
        raise TypeError(
            "unregistered fitted model type; external baselines require a versioned "
            f"adapter artifact, got {type(model).__module__}.{type(model).__qualname__}"
        )
    return {
        "schema": "compose_fitted_model_v1",
        "implementation": f"{type(model).__module__}.{type(model).__qualname__}",
        "state": state,
    }


def fitted_model_checksum(model: SymmetricModel) -> str:
    """SHA-256 of :func:`fitted_model_artifact`."""
    return sha256_json(fitted_model_artifact(model))
