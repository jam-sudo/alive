"""Frozen Phase-2a -> Phase-2b prediction handoff (Task 2a-11, plan §2.5).

SYNTHETIC-ONLY: pure ``numpy`` + JSON on synthetic inputs only; **NO seal
access** and **NO measured sealed outcome** ever enters this module.

The :class:`FrozenPredictionBundle` is the single artifact Phase 2b consumes
without refitting. It carries (plan §2.5):

* the composite ``run_id``;
* the exact registered method roster;
* the sealed pair IDs grouped by ``sealed_double_unseen`` / ``sealed_single_unseen``;
* **predictions only** — one length-``response_dim`` vector per (method, pair) —
  and **never** a measured pair outcome;
* the response-space, factor, model and manifest checksums;
* the per-method fitted-model / adapter-execution artifact checksums used to
  derive the aggregate model checksum;
* the selected hyperparameters and registered seeds;
* the development diagnostics and futility status.

Two leakage walls are enforced at *construction*:

1. :func:`alive.compose.baselines_combo._assert_no_sealed_reference` (reused) walks
   every nested string in the diagnostics, roster and IDs and refuses any sealed
   role / sealed key / sealed path at any depth; and
2. :func:`_assert_no_outcome_reference` refuses any measured-outcome marker
   (``measured`` / ``truth`` / ``observed`` / ``eps_obs`` / ``outcome`` / ...) so
   no observed array can be smuggled in through the free-form diagnostics.

The bundle is **write-once** and self-verifying: :meth:`create` seals a SHA-256
``bundle_checksum`` over the canonical payload (run_id + roster + IDs +
predictions + every upstream checksum + selected hyperparameters/seeds +
diagnostics). :meth:`verify` recomputes that checksum and re-runs the
per-prediction validity checks, so mutating ANY upstream artifact, recorded
checksum, or prediction after freezing fails verification.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from alive.compose.baselines_combo import _assert_no_sealed_reference
from alive.io import atomic_write_once
from alive.provenance import sha256_json

#: Exact pre-registered method roster required by the Phase-2b comparison family.
REQUIRED_METHODS: tuple[str, ...] = (
    "l1_bilinear_identifiable",
    "l2_saturation",
    "l3_hypernetwork",
    "additive",
    "no_change",
    "perturbation_mean",
    "id_only",
    "gears",
    "cpa",
)

NON_ARTIFACT_METHODS: frozenset[str] = frozenset({"additive", "no_change", "perturbation_mean"})

#: Substrings that mark a *measured outcome* (vs a prediction). The bundle holds
#: predictions only, so any of these appearing as a key/value/path anywhere in the
#: free-form diagnostics or identities is refused at construction (plan §2.5).
OUTCOME_TOKENS: tuple[str, ...] = (
    "measured",
    "truth",
    "y_true",
    "observed",
    "observation",
    "eps_obs",
    "outcome",
    "ground_truth",
)


class FreezeError(ValueError):
    """Raised on an invalid bundle, a failed checksum verification, or a re-write.

    Covers (a) an incomplete/duplicated method roster, (b) a prediction that is
    non-finite, wrong-shaped, non-canonical, missing or extra, (c) a
    :meth:`FrozenPredictionBundle.verify` checksum mismatch after tampering, and
    (d) a write-once violation.
    """


class OutcomeLeakageError(ValueError):
    """Raised when a measured sealed outcome (not a prediction) enters the bundle.

    The bundle is predictions-only. A measured-outcome marker anywhere in the
    free-form diagnostics or identities — or any sealed role / sealed key / sealed
    path — raises this rather than being silently accepted.
    """


def _assert_no_sealed(obj: object) -> None:
    """Reuse the recursive sealed-reference scanner, re-raising as a bundle error.

    Delegates to
    :func:`alive.compose.baselines_combo._assert_no_sealed_reference` (the single
    source of the recursive sealed-role / sealed-key / sealed-path walk) and
    normalises its :class:`ValueError` to :class:`OutcomeLeakageError` so the
    bundle boundary raises one consistent leakage type.

    Raises
    ------
    OutcomeLeakageError
        If any sealed reference is present anywhere in ``obj``.
    """
    try:
        _assert_no_sealed_reference(obj)
    except ValueError as exc:  # the scanner raises ValueError on a sealed token
        raise OutcomeLeakageError(str(exc)) from exc


def _assert_no_outcome_reference(obj: object) -> None:
    """Recursively refuse any *measured-outcome* marker anywhere in ``obj``.

    Mirrors the recursive walk of
    :func:`alive.compose.baselines_combo._assert_no_sealed_reference` but checks
    against :data:`OUTCOME_TOKENS` (case-folded). Every string — whether a mapping
    key, a value, a set member or a sequence element — is checked at any nesting
    depth so a measured array smuggled deep into the diagnostics is caught.

    Parameters
    ----------
    obj : object
        Any nested structure (mapping / sequence / set / dataclass / scalar).

    Raises
    ------
    OutcomeLeakageError
        If any string anywhere in ``obj`` contains a measured-outcome token.
    """
    stack: list[object] = [obj]
    seen: set[int] = set()
    # `seen` is keyed on id(), and the numpy branches below materialise NEW
    # temporaries (``tolist()`` elements, structured-array field views) that
    # nothing else references. Pinning every visited object prevents CPython from
    # recycling a freed address into a later temporary, which the id-keyed set
    # would then treat as already-scanned and skip — a silent fail-open.
    visited: list[object] = []
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        visited.append(cur)

        if isinstance(cur, str):
            lowered = cur.casefold()
            if any(token in lowered for token in OUTCOME_TOKENS):
                raise OutcomeLeakageError(
                    f"measured-outcome reference detected (bundle is predictions-only): {cur!r}"
                )
            continue
        if isinstance(cur, (bytes, bytearray, np.bytes_)):
            try:
                decoded = bytes(cur).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OutcomeLeakageError(
                    "non-UTF-8 byte string is not permitted in predictions-only diagnostics"
                ) from exc
            lowered = decoded.casefold()
            if any(token in lowered for token in OUTCOME_TOKENS):
                raise OutcomeLeakageError(
                    f"measured-outcome reference detected (bundle is predictions-only): {decoded!r}"
                )
            continue
        if hasattr(cur, "__dataclass_fields__"):
            for fname in cur.__dataclass_fields__:  # type: ignore[attr-defined]
                stack.append(fname)
                stack.append(getattr(cur, fname))
            continue
        if isinstance(cur, Mapping):
            for key, val in cur.items():
                stack.append(key)
                stack.append(val)
            continue
        if isinstance(cur, (set, frozenset)):
            stack.extend(cur)
            continue
        if isinstance(cur, Sequence):
            stack.extend(cur)
            continue
        if isinstance(cur, np.ndarray) and cur.dtype.fields is not None:
            stack.extend(cur[name] for name in cur.dtype.names or ())
            continue
        if isinstance(cur, np.ndarray) and cur.dtype.kind in {"U", "S", "O"}:
            stack.extend(cur.ravel().tolist())
            continue
        # scalars / numeric numpy arrays: nothing string-bearing to scan


def _is_canonical(pair: tuple[str, str]) -> bool:
    """Return ``True`` if ``pair`` is canonical ``(min, max)`` by UTF-8 bytes."""
    g, h = pair
    return g.encode("utf-8") <= h.encode("utf-8")


def _validate_model_artifact_binding(
    method_roster: tuple[str, ...],
    model_artifact_checksums: Mapping[str, str],
    model_checksum: str,
    selected_k_total: int,
    selected_lambda: float,
) -> dict[str, str]:
    """Validate the complete method-artifact map and its aggregate checksum."""
    if not isinstance(model_artifact_checksums, Mapping):
        raise FreezeError("model_artifact_checksums must be a mapping")
    invalid_keys = [repr(key) for key in model_artifact_checksums if not isinstance(key, str)]
    if invalid_keys:
        raise FreezeError(f"model artifact checksum keys must be strings: {invalid_keys}")
    expected_methods = set(method_roster) - NON_ARTIFACT_METHODS
    supplied_methods = set(model_artifact_checksums)
    if supplied_methods != expected_methods:
        raise FreezeError(
            "model artifact checksum roster mismatch "
            f"(missing={sorted(expected_methods - supplied_methods)}, "
            f"extra={sorted(supplied_methods - expected_methods)})"
        )
    malformed = {
        name: digest
        for name, digest in model_artifact_checksums.items()
        if not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    }
    if malformed:
        raise FreezeError(
            "model artifact checksums must be 64 lowercase hexadecimal characters "
            f"for {sorted(malformed)}"
        )
    snapshot = {name: model_artifact_checksums[name] for name in sorted(model_artifact_checksums)}
    expected_checksum = sha256_json(
        {
            "schema": "compose_model_set_v1",
            "methods": snapshot,
            "selected_k_total": int(selected_k_total),
            "selected_lambda": float(selected_lambda).hex(),
        }
    )
    if model_checksum != expected_checksum:
        raise FreezeError(
            "model checksum does not bind the supplied per-method artifact checksums "
            "and selected hyperparameters"
        )
    return snapshot


def _validate_role_predictions(
    role: str,
    method_roster: tuple[str, ...],
    pair_ids: tuple[tuple[str, str], ...],
    predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
    response_dim: int,
) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    """Validate every prediction for one sealed role and return a copied mapping.

    Parameters
    ----------
    role : str
        ``"sealed_double_unseen"`` or ``"sealed_single_unseen"`` (for messages).
    method_roster : tuple of str
        The complete registered method roster; every method must predict every
        registered pair, and no other method may appear.
    pair_ids : tuple of tuple of str
        The registered canonical sealed pair IDs for this role.
    predictions : Mapping
        ``method -> {pair_id -> vector}``.
    response_dim : int
        Required length of every prediction vector.

    Returns
    -------
    dict
        ``method -> {pair_id -> float ndarray}`` validated and copied.

    Raises
    ------
    FreezeError
        For a non-canonical registered pair, a roster/method mismatch, an extra /
        missing / non-canonical pair, or a non-finite / wrong-shape prediction.
    """
    registered = set(pair_ids)
    if len(registered) != len(pair_ids):
        raise FreezeError(f"{role}: duplicate registered pair IDs")
    for pair in pair_ids:
        if len(pair) != 2 or not all(isinstance(x, str) for x in pair):
            raise FreezeError(f"{role}: registered pair must be a (str, str) tuple, got {pair!r}")
        if not _is_canonical(pair):
            raise FreezeError(f"{role}: registered pair is not canonical (min, max): {pair!r}")

    pred_methods = set(predictions)
    roster_set = set(method_roster)
    extra_methods = pred_methods - roster_set
    if extra_methods:
        raise FreezeError(f"{role}: predictions for non-roster methods: {sorted(extra_methods)}")
    missing_methods = roster_set - pred_methods
    if missing_methods:
        raise FreezeError(f"{role}: roster methods missing predictions: {sorted(missing_methods)}")

    out: dict[str, dict[tuple[str, str], np.ndarray]] = {}
    for method in method_roster:
        method_preds = predictions[method]
        keys = set()
        for key in method_preds:
            items = tuple(key)
            if len(items) != 2 or not all(isinstance(x, str) for x in items):
                raise FreezeError(f"{role}/{method}: non-pair prediction key {key!r}")
            keys.add(items)
        extra = keys - registered
        if extra:
            raise FreezeError(
                f"{role}/{method}: predictions for unregistered pairs {sorted(extra)}"
            )
        missing = registered - keys
        if missing:
            raise FreezeError(f"{role}/{method}: missing predictions for pairs {sorted(missing)}")

        method_out: dict[tuple[str, str], np.ndarray] = {}
        for pair, vec in method_preds.items():
            arr = np.array(vec, dtype=np.float64, copy=True)
            if arr.shape != (response_dim,):
                raise FreezeError(
                    f"{role}/{method}: prediction for {pair!r} has shape {arr.shape}, "
                    f"expected dimension ({response_dim},)"
                )
            if not np.all(np.isfinite(arr)):
                raise FreezeError(f"{role}/{method}: prediction for {pair!r} is not finite")
            arr.setflags(write=False)
            method_out[tuple(pair)] = arr
        out[method] = method_out
    return out


def _predictions_payload(
    predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
) -> dict[str, dict[str, list[str]]]:
    """Canonical, lossless JSON-serialisable predictions payload.

    Pair keys ``(g, h)`` are flattened with a tab separator (``"g\th"``) so the
    mapping is JSON-serialisable; values are encoded as exact float64 hexadecimal
    strings so every prediction bit is bound.
    """
    payload: dict[str, dict[str, list[str]]] = {}
    for method in sorted(predictions):
        method_block: dict[str, list[str]] = {}
        for pair in sorted(predictions[method]):
            vec = np.asarray(predictions[method][pair], dtype=float)
            method_block["\t".join(pair)] = [float(v).hex() for v in vec.tolist()]
        payload[method] = method_block
    return payload


def _predictions_from_payload(
    payload: Mapping[str, Mapping[str, Sequence[float | str]]],
) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    """Inverse of :func:`_predictions_payload` (used by :meth:`from_dict`)."""
    out: dict[str, dict[tuple[str, str], np.ndarray]] = {}
    for method, block in payload.items():
        method_out: dict[tuple[str, str], np.ndarray] = {}
        for flat, vec in block.items():
            g, h = flat.split("\t")
            arr = np.asarray(
                [float.fromhex(v) if isinstance(v, str) else float(v) for v in vec],
                dtype=np.float64,
            )
            arr.setflags(write=False)
            method_out[(g, h)] = arr
        out[method] = method_out
    return out


@dataclass(frozen=True)
class FrozenPredictionBundle:
    """The frozen, predictions-only Phase-2a -> Phase-2b handoff (plan §2.5).

    Construct via :meth:`create`, which validates every prediction, runs both
    leakage walls (no sealed reference, no measured outcome) and seals the
    self-excluding ``bundle_checksum``. The bundle contains predictions only;
    measured sealed outcomes are never present.

    Attributes
    ----------
    run_id : str
        Composite COMPOSE run identifier.
    method_roster : tuple of str
        The exact registered method roster.
    pair_ids_double_unseen : tuple of tuple of str
        Registered canonical ``sealed_double_unseen`` pair IDs.
    pair_ids_single_unseen : tuple of tuple of str
        Registered canonical ``sealed_single_unseen`` pair IDs.
    predictions_double_unseen : dict
        ``method -> {pair_id -> length-response_dim vector}`` for the
        ``sealed_double_unseen`` role. Predictions only.
    predictions_single_unseen : dict
        As above for the ``sealed_single_unseen`` role.
    response_space_checksum, factor_checksum, model_checksum, manifest_checksum :
        str. Upstream artifact checksums this bundle is bound to.
    model_artifact_checksums : dict
        Complete ``method -> SHA-256`` mapping for fitted models and external
        adapter executions. The aggregate ``model_checksum`` is recomputed from
        this mapping and the selected hyperparameters.
    selected_k_total : int
        Selected total factor dimension.
    selected_lambda : float
        Selected ridge regularization.
    registered_seeds : tuple of int
        Registered random seeds.
    futility_status : str
        Development futility status (``"CONTINUE"`` for a freezing run).
    dev_diagnostics : dict
        Free-form development diagnostics (no outcomes, no sealed reference).
    response_dim : int
        Response dimension of every prediction vector.
    bundle_checksum : str
        Self-excluding SHA-256 over the canonical payload (set by :meth:`create`).
    """

    run_id: str
    method_roster: tuple[str, ...]
    pair_ids_double_unseen: tuple[tuple[str, str], ...]
    pair_ids_single_unseen: tuple[tuple[str, str], ...]
    predictions_double_unseen: dict[str, dict[tuple[str, str], np.ndarray]]
    predictions_single_unseen: dict[str, dict[tuple[str, str], np.ndarray]]
    response_space_checksum: str
    factor_checksum: str
    model_checksum: str
    model_artifact_checksums: dict[str, str]
    manifest_checksum: str
    selected_k_total: int
    selected_lambda: float
    registered_seeds: tuple[int, ...]
    futility_status: str
    dev_diagnostics: dict
    response_dim: int
    bundle_checksum: str = field(default="")

    # -- construction ----------------------------------------------------- #
    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        method_roster: Sequence[str],
        pair_ids_double_unseen: Sequence[tuple[str, str]],
        pair_ids_single_unseen: Sequence[tuple[str, str]],
        predictions_double_unseen: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
        predictions_single_unseen: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
        response_space_checksum: str,
        factor_checksum: str,
        model_checksum: str,
        model_artifact_checksums: Mapping[str, str],
        manifest_checksum: str,
        selected_k_total: int,
        selected_lambda: float,
        registered_seeds: Sequence[int],
        futility_status: str,
        dev_diagnostics: Mapping,
        response_dim: int,
        required_roster: Sequence[str] | None = None,
    ) -> "FrozenPredictionBundle":
        """Validate, run both leakage walls, and seal the bundle checksum.

        Parameters
        ----------
        run_id, response_space_checksum, factor_checksum, model_checksum,
        manifest_checksum, selected_k_total, selected_lambda, registered_seeds,
        futility_status, response_dim
            Recorded verbatim into the checksummed payload.
        model_artifact_checksums : Mapping[str, str]
            Exact fitted-model / adapter-execution checksum roster. Its keys must
            equal every non-analytic method in ``method_roster`` and its contents
            must derive ``model_checksum`` with the selected hyperparameters.
        method_roster : sequence of str
            The complete registered method roster. Must equal ``required_roster``
            when supplied; must be non-empty and unique otherwise.
        pair_ids_double_unseen, pair_ids_single_unseen : sequence of (str, str)
            Registered canonical sealed pair IDs per role.
        predictions_double_unseen, predictions_single_unseen : Mapping
            ``method -> {pair_id -> vector}`` per role; predictions only.
        dev_diagnostics : Mapping
            Free-form development diagnostics. Scanned for sealed references and
            measured outcomes; either raises.
        required_roster : sequence of str or None, optional
            When supplied, ``method_roster`` must equal it exactly (the registered
            roster from the orchestrator / config).

        Returns
        -------
        FrozenPredictionBundle
            The sealed, self-verifying bundle.

        Raises
        ------
        FreezeError
            On an incomplete/duplicated roster or any invalid prediction.
        OutcomeLeakageError
            If a sealed reference or a measured-outcome marker is present anywhere.
        """
        roster = tuple(method_roster)
        diagnostics = dict(dev_diagnostics)

        # leakage wall 1 (run FIRST, before any roster/prediction logic): no sealed
        # role / sealed key / sealed path anywhere in the roster or diagnostics
        # (reused recursive scanner, re-raised as OutcomeLeakageError).
        _assert_no_sealed(roster)
        _assert_no_sealed(diagnostics)
        # leakage wall 2: no measured-outcome marker anywhere (predictions-only).
        _assert_no_outcome_reference(roster)
        _assert_no_outcome_reference(diagnostics)

        if not roster:
            raise FreezeError("method roster must be non-empty")
        if len(set(roster)) != len(roster):
            raise FreezeError(f"method roster has duplicates: {roster}")
        required = tuple(required_roster) if required_roster is not None else REQUIRED_METHODS
        if roster != required:
            raise FreezeError(
                "method roster must equal the registered roster exactly "
                f"(roster={roster}, required={required})"
            )

        double_ids = tuple(tuple(p) for p in pair_ids_double_unseen)
        single_ids = tuple(tuple(p) for p in pair_ids_single_unseen)

        validated_double = _validate_role_predictions(
            "sealed_double_unseen", roster, double_ids, predictions_double_unseen, response_dim
        )
        validated_single = _validate_role_predictions(
            "sealed_single_unseen", roster, single_ids, predictions_single_unseen, response_dim
        )
        validated_model_artifacts = _validate_model_artifact_binding(
            roster,
            model_artifact_checksums,
            str(model_checksum),
            int(selected_k_total),
            float(selected_lambda),
        )

        bundle = cls(
            run_id=str(run_id),
            method_roster=roster,
            pair_ids_double_unseen=double_ids,
            pair_ids_single_unseen=single_ids,
            predictions_double_unseen=validated_double,
            predictions_single_unseen=validated_single,
            response_space_checksum=str(response_space_checksum),
            factor_checksum=str(factor_checksum),
            model_checksum=str(model_checksum),
            model_artifact_checksums=validated_model_artifacts,
            manifest_checksum=str(manifest_checksum),
            selected_k_total=int(selected_k_total),
            selected_lambda=float(selected_lambda),
            registered_seeds=tuple(int(s) for s in registered_seeds),
            futility_status=str(futility_status),
            dev_diagnostics=diagnostics,
            response_dim=int(response_dim),
        )

        checksum = sha256_json(bundle._payload())
        object.__setattr__(bundle, "bundle_checksum", checksum)
        return bundle

    # -- canonical payload + checksum ------------------------------------- #
    def _payload(self) -> dict:
        """Canonical, JSON-serialisable payload (the checksum input; excludes it)."""
        return {
            "run_id": self.run_id,
            "method_roster": list(self.method_roster),
            "pair_ids_double_unseen": [list(p) for p in self.pair_ids_double_unseen],
            "pair_ids_single_unseen": [list(p) for p in self.pair_ids_single_unseen],
            "predictions_double_unseen": _predictions_payload(self.predictions_double_unseen),
            "predictions_single_unseen": _predictions_payload(self.predictions_single_unseen),
            "response_space_checksum": self.response_space_checksum,
            "factor_checksum": self.factor_checksum,
            "model_checksum": self.model_checksum,
            "model_artifact_checksums": self.model_artifact_checksums,
            "manifest_checksum": self.manifest_checksum,
            "selected_k_total": int(self.selected_k_total),
            "selected_lambda": round(float(self.selected_lambda), 12),
            "registered_seeds": list(self.registered_seeds),
            "futility_status": self.futility_status,
            "dev_diagnostics": self.dev_diagnostics,
            "response_dim": int(self.response_dim),
        }

    # -- verification ----------------------------------------------------- #
    def verify(self) -> None:
        """Recompute the checksum and re-validate predictions; raise on tampering.

        Recomputes the canonical-payload SHA-256 and compares it to the sealed
        ``bundle_checksum``, then re-runs the per-prediction validity checks. Any
        post-freeze mutation of a recorded checksum, the ``run_id``, the
        hyperparameters, the diagnostics, or a prediction value changes the
        recomputed checksum and raises.

        Raises
        ------
        FreezeError
            If the recomputed checksum differs from the sealed one or any
            prediction is no longer valid.
        """
        # re-validate predictions (catches shape/finiteness corruption directly).
        _validate_role_predictions(
            "sealed_double_unseen",
            self.method_roster,
            self.pair_ids_double_unseen,
            self.predictions_double_unseen,
            self.response_dim,
        )
        _validate_role_predictions(
            "sealed_single_unseen",
            self.method_roster,
            self.pair_ids_single_unseen,
            self.predictions_single_unseen,
            self.response_dim,
        )
        _validate_model_artifact_binding(
            self.method_roster,
            self.model_artifact_checksums,
            self.model_checksum,
            self.selected_k_total,
            self.selected_lambda,
        )
        recomputed = sha256_json(self._payload())
        if recomputed != self.bundle_checksum:
            raise FreezeError(
                "bundle checksum mismatch: an upstream artifact, recorded checksum, "
                "or prediction was mutated after freezing "
                f"(recomputed {recomputed[:12]}..., sealed {self.bundle_checksum[:12]}...)"
            )

    def assert_no_outcomes(self) -> None:
        """Assert the bundle holds predictions only (no measured outcomes).

        Re-runs both leakage walls over the roster, identities and diagnostics.

        Raises
        ------
        OutcomeLeakageError
            If a sealed reference or measured-outcome marker is present.
        """
        _assert_no_sealed(self.method_roster)
        _assert_no_sealed(self.dev_diagnostics)
        _assert_no_outcome_reference(self.method_roster)
        _assert_no_outcome_reference(self.dev_diagnostics)

    # -- serialisation ---------------------------------------------------- #
    def to_dict(self) -> dict:
        """Return the canonical payload augmented with the sealed checksum."""
        rep = self._payload()
        rep["bundle_checksum"] = self.bundle_checksum
        return rep

    @classmethod
    def from_dict(cls, data: Mapping) -> "FrozenPredictionBundle":
        """Reconstruct a bundle from :meth:`to_dict` output (checksum preserved)."""
        double_ids = tuple(tuple(p) for p in data["pair_ids_double_unseen"])
        single_ids = tuple(tuple(p) for p in data["pair_ids_single_unseen"])
        bundle = cls(
            run_id=data["run_id"],
            method_roster=tuple(data["method_roster"]),
            pair_ids_double_unseen=double_ids,
            pair_ids_single_unseen=single_ids,
            predictions_double_unseen=_predictions_from_payload(data["predictions_double_unseen"]),
            predictions_single_unseen=_predictions_from_payload(data["predictions_single_unseen"]),
            response_space_checksum=data["response_space_checksum"],
            factor_checksum=data["factor_checksum"],
            model_checksum=data["model_checksum"],
            model_artifact_checksums=dict(data["model_artifact_checksums"]),
            manifest_checksum=data["manifest_checksum"],
            selected_k_total=int(data["selected_k_total"]),
            selected_lambda=float(data["selected_lambda"]),
            registered_seeds=tuple(int(s) for s in data["registered_seeds"]),
            futility_status=data["futility_status"],
            dev_diagnostics=dict(data["dev_diagnostics"]),
            response_dim=int(data["response_dim"]),
            bundle_checksum=data.get("bundle_checksum", ""),
        )
        return bundle

    def write(self, path: str | Path) -> None:
        """Write the bundle to ``path`` as canonical JSON (write-once).

        Parameters
        ----------
        path : str or Path
            Destination file. Must not already exist (the bundle is written ONCE
            per the run-immutability contract, CLAUDE.md#provenance).

        Raises
        ------
        FreezeError
            If ``path`` already exists.
        """
        path = Path(path)
        try:
            atomic_write_once(
                path,
                json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")),
            )
        except FileExistsError as exc:
            raise FreezeError(
                f"refusing to overwrite existing bundle at {path}: the frozen bundle "
                "is write-once (CLAUDE.md#provenance)"
            ) from exc

    @classmethod
    def load(cls, path: str | Path) -> "FrozenPredictionBundle":
        """Load a bundle written by :meth:`write` (call :meth:`verify` after)."""
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)
