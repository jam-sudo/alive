"""Combo lower-bound baselines + a GUARDED GEARS/CPA adapter seam (Phase 2a).

SYNTHETIC-ONLY. This module is pure ``numpy`` and adds **no** real
``gears`` / ``cpa`` package dependency. It provides:

* the registered lower-bound / null baselines
  (:func:`additive`, :func:`no_change`, :func:`perturbation_mean`) as simple,
  symmetric, pure functions; and
* a guarded :class:`BaselineAdapter` seam for the deep combo baselines (GEARS,
  CPA). The real backends are injected only at activation (plan blocker #4), so
  the seam accepts an arbitrary ``backend`` object — in tests an in-memory stub —
  and an unavailable backend raises :class:`BaselineUnavailable`.

Leakage contract (plan §2.1, task brief)
----------------------------------------

The adapter receives a :class:`BaselineTrainingContext`: a **frozen** typed
object that carries development-role identities and checksums only. It holds
**no** outcome-store handle and **no** sealed paths. Before any backend call the
adapter:

1. rejects anything that is not a :class:`BaselineTrainingContext`
   (arbitrary untyped dictionaries cannot enter a Phase-2a public API);
2. requires ``allowed_roles == {"singles", "combo_calibration"}`` *exactly*
   (no missing role, no superset, no sealed role); and
3. **recursively** scans every nested string in the context for a sealed role,
   sealed outcome key or path to a sealed asset
   (:func:`_assert_no_sealed_reference`) and refuses if any is found.

After the backend returns, its output is validated against the requested
canonical pair IDs and response dimension *exactly*: extra, missing,
non-canonical/misaligned keys, or a wrong response dimension all raise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

#: Roles the deep combo adapters are permitted to train on — exactly this set.
ALLOWED_ADAPTER_ROLES: frozenset[str] = frozenset({"singles", "combo_calibration"})

#: Substrings that mark a sealed role / sealed outcome key / path to a sealed
#: asset. The recursive scanner refuses any string containing one of these.
SEALED_TOKENS: tuple[str, ...] = (
    "sealed_double_unseen",
    "sealed_single_unseen",
    "sealed",
)


class BaselineUnavailable(RuntimeError):
    """Raised when a guarded adapter has no available backend.

    The real GEARS/CPA backends are injected only at activation. Until then the
    seam exists but cannot produce predictions, and callers must handle this
    explicitly rather than silently substituting a mock.
    """


# --------------------------------------------------------------------------- #
# lower-bound / null baselines
# --------------------------------------------------------------------------- #


def additive(delta_g: np.ndarray, delta_h: np.ndarray) -> np.ndarray:
    """Additive (no-interaction) baseline: ``delta_g + delta_h``.

    This is the canonical null hypothesis for genetic interaction — the double
    perturbation response equals the sum of the two single-gene shifts. It is
    symmetric in its arguments by construction.

    Parameters
    ----------
    delta_g : numpy.ndarray
        Single-gene response shift for gene ``g`` (length ``p``).
    delta_h : numpy.ndarray
        Single-gene response shift for gene ``h`` (length ``p``).

    Returns
    -------
    numpy.ndarray
        The element-wise sum ``delta_g + delta_h`` (length ``p``).

    Raises
    ------
    ValueError
        If the two shifts do not have identical shape.
    """
    a = np.asarray(delta_g, dtype=float)
    b = np.asarray(delta_h, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"single-gene shifts must share shape, got {a.shape} and {b.shape}")
    return a + b


def no_change(response_dim: int) -> np.ndarray:
    """No-change (zero) baseline: a zero vector of length ``response_dim``.

    Predicts that the double perturbation produces no shift in the response
    space — the weakest possible non-informative baseline.

    Parameters
    ----------
    response_dim : int
        Dimensionality of the response space; must be positive.

    Returns
    -------
    numpy.ndarray
        ``numpy.zeros(response_dim)``.

    Raises
    ------
    ValueError
        If ``response_dim`` is not a positive integer.
    """
    if int(response_dim) <= 0:
        raise ValueError(f"response_dim must be a positive integer, got {response_dim!r}")
    return np.zeros(int(response_dim), dtype=float)


def perturbation_mean(training_double_shifts: np.ndarray) -> np.ndarray:
    """Perturbation-mean baseline: mean double shift over **training** roles.

    Predicts the same vector for every pair: the mean of the observed double
    perturbation shifts on the development (calibration) role. This is fitted on
    training-role outcomes only; sealed double outcomes never enter here.

    Parameters
    ----------
    training_double_shifts : numpy.ndarray
        Array of shape ``(n_train_pairs, p)`` of observed double shifts on the
        development role. Must be non-empty.

    Returns
    -------
    numpy.ndarray
        The column-wise mean, length ``p``.

    Raises
    ------
    ValueError
        If the input is not a non-empty 2-D array.
    """
    arr = np.asarray(training_double_shifts, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0:
        raise ValueError(
            f"training_double_shifts must be a non-empty (n_pairs, p) array, got shape {arr.shape}"
        )
    return arr.mean(axis=0)


# --------------------------------------------------------------------------- #
# frozen training context — no seal handle, no sealed paths
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BaselineTrainingContext:
    """Frozen, typed development-role context handed to a guarded adapter.

    The context carries **identities and checksums only**. It deliberately holds
    NO outcome-store handle and NO sealed paths, so a deep combo backend cannot
    reach a sealed outcome through it. Public Phase-2a adapters accept this typed
    object, never an arbitrary dictionary (plan §2.1).

    Attributes
    ----------
    allowed_roles : frozenset of str
        The roles the backend may train on. The adapter requires this to equal
        :data:`ALLOWED_ADAPTER_ROLES` exactly.
    pair_manifest_checksum : str
        Checksum of the pair-split manifest this context is bound to.
    response_space_checksum : str
        Checksum of the frozen response-space artifact.
    training_pair_ids : tuple of tuple of str
        Canonical development (calibration) pair IDs available for fitting.
    single_gene_ids : tuple of str
        Single-gene IDs available for fitting.
    """

    allowed_roles: frozenset[str]
    pair_manifest_checksum: str
    response_space_checksum: str
    training_pair_ids: tuple[tuple[str, str], ...]
    single_gene_ids: tuple[str, ...]


# --------------------------------------------------------------------------- #
# recursive sealed-reference scanner
# --------------------------------------------------------------------------- #


def _string_is_sealed(value: str) -> bool:
    """Return ``True`` if ``value`` contains any sealed token (case-folded)."""
    lowered = value.casefold()
    return any(token in lowered for token in SEALED_TOKENS)


def _assert_no_sealed_reference(obj: object) -> None:
    """Recursively refuse any sealed role / sealed key / sealed path.

    Walks an arbitrary nested structure of mappings, sequences, sets, tuples and
    dataclasses. Every string encountered — whether a *key*, a *value*, a set
    member or a path-like fragment — is checked against :data:`SEALED_TOKENS`.
    The scan therefore fires on a sealed token buried at any nesting depth, not
    just at the top level.

    Bytes are kept out by design: only ``str`` carries a sealed token here, and
    the context fields are all strings/tuples-of-strings.

    Parameters
    ----------
    obj : object
        Any nested structure (e.g. a :class:`BaselineTrainingContext`, a dict,
        list, tuple or set) to scan.

    Raises
    ------
    ValueError
        If any string anywhere in ``obj`` contains a sealed token.
    """
    stack: list[object] = [obj]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        # avoid pathological re-visits of shared/cyclic containers
        if id(cur) in seen:
            continue
        seen.add(id(cur))

        if isinstance(cur, str):
            if _string_is_sealed(cur):
                raise ValueError(f"sealed reference detected in context: {cur!r}")
            continue
        if isinstance(cur, (bytes, bytearray)):
            continue
        # dataclass instances: scan their field values
        if hasattr(cur, "__dataclass_fields__"):
            for field_name in cur.__dataclass_fields__:  # type: ignore[attr-defined]
                if _string_is_sealed(field_name):
                    raise ValueError(f"sealed reference detected in field name: {field_name!r}")
                stack.append(getattr(cur, field_name))
            continue
        if isinstance(cur, Mapping):
            for key, val in cur.items():
                if isinstance(key, str) and _string_is_sealed(key):
                    raise ValueError(f"sealed reference detected in key: {key!r}")
                stack.append(key)
                stack.append(val)
            continue
        if isinstance(cur, (set, frozenset)):
            stack.extend(cur)
            continue
        # ordered sequences (but not str/bytes, handled above)
        if isinstance(cur, Sequence):
            stack.extend(cur)
            continue
        # scalars / numpy arrays / anything else: nothing string-bearing to scan


# --------------------------------------------------------------------------- #
# guarded GEARS/CPA adapter seam
# --------------------------------------------------------------------------- #


@dataclass
class BaselineAdapter:
    """Guarded seam for a deep combo baseline backend (GEARS / CPA).

    The real backends are injected at activation (plan blocker #4). For
    stub-testable development the adapter accepts any object exposing
    ``is_available: bool`` and
    ``predict(context, pair_ids, response_dim) -> Mapping[pair, ndarray]``.

    Every leakage guard runs *before* the backend is touched, and the backend
    output is validated *exactly* against the request afterward.

    Attributes
    ----------
    name : str
        Human-readable adapter name (e.g. ``"gears"`` or ``"cpa"``); used only
        in error/diagnostic messages.
    backend : object or None
        The injected backend. ``None`` (or an unavailable backend) causes
        :meth:`predict` to raise :class:`BaselineUnavailable`.
    """

    name: str
    backend: object | None = None

    def spawn(self, *, seed: int) -> "BaselineAdapter":
        """Return a fresh adapter wrapping a freshly spawned backend for one seed.

        D2 requires an isolated backend per ``(method, seed, fold)`` job, so the
        wrapped backend MUST expose the ``spawn(*, seed)`` fresh-instance contract.
        A ``None`` backend, or a backend without a callable ``spawn`` — e.g. a
        test-only stub — is rejected here, *before any fit*, so a non-spawnable
        backend can never enter a scientific seed-variability run.

        Parameters
        ----------
        seed : int
            The seed forwarded to the wrapped backend's ``spawn``.

        Returns
        -------
        BaselineAdapter
            A new adapter with the same ``name`` wrapping
            ``backend.spawn(seed=seed)``.

        Raises
        ------
        TypeError
            If the wrapped backend is ``None`` or does not expose a callable
            ``spawn`` — the scientific D2 rejection of a non-spawnable backend.
        """
        backend = self.backend
        if backend is None or not callable(getattr(backend, "spawn", None)):
            raise TypeError(
                f"{self.name} adapter requires a backend exposing a callable "
                f"spawn(*, seed); got {type(backend).__name__}"
            )
        return BaselineAdapter(name=self.name, backend=backend.spawn(seed=seed))

    def predict(
        self,
        context: BaselineTrainingContext,
        pair_ids: list[tuple[str, str]],
        response_dim: int,
    ) -> dict[tuple[str, str], np.ndarray]:
        """Validate the context, call the backend, validate its output.

        Parameters
        ----------
        context : BaselineTrainingContext
            The frozen development-role context. Must be exactly this type, carry
            exactly the allowed roles and contain no sealed reference anywhere.
        pair_ids : list of tuple of str
            The canonical pair IDs to predict (request order is irrelevant).
        response_dim : int
            The required response dimension for every prediction vector.

        Returns
        -------
        dict
            Mapping from each requested canonical pair ID to a
            length-``response_dim`` prediction vector.

        Raises
        ------
        TypeError
            If ``context`` is not a :class:`BaselineTrainingContext`.
        ValueError
            If ``allowed_roles`` is not exactly :data:`ALLOWED_ADAPTER_ROLES`, if
            any sealed reference is present, or if the backend output does not
            match the requested pair IDs / response dimension exactly.
        BaselineUnavailable
            If no available backend is injected.
        """
        # 1. typed-object gate: arbitrary untyped dicts cannot enter.
        if not isinstance(context, BaselineTrainingContext):
            raise TypeError(
                f"{self.name} adapter requires a BaselineTrainingContext, "
                f"got {type(context).__name__}"
            )

        # 2. exact-role gate (also catches sealed roles in allowed_roles).
        if frozenset(context.allowed_roles) != ALLOWED_ADAPTER_ROLES:
            raise ValueError(
                f"{self.name} adapter requires allowed_roles == "
                f"{set(ALLOWED_ADAPTER_ROLES)}, got {set(context.allowed_roles)}"
            )

        # 3. recursive sealed-role / sealed-key / sealed-path rejection.
        _assert_no_sealed_reference(context)

        # 4. backend availability.
        backend = self.backend
        if backend is None or not getattr(backend, "is_available", False):
            raise BaselineUnavailable(
                f"{self.name} backend is not available; real GEARS/CPA backends "
                "are injected only at activation"
            )

        requested = _canonical_pair_set(pair_ids)

        raw = backend.predict(context, list(pair_ids), int(response_dim))
        return _validate_backend_output(self.name, raw, requested, int(response_dim))


def _canonical_pair_set(pair_ids: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """Return the requested pair IDs as a set, asserting they are canonical.

    Raises
    ------
    ValueError
        If any requested pair is not a canonical 2-tuple ``(min, max)`` by UTF-8
        byte order, or if duplicate pairs are requested.
    """
    out: set[tuple[str, str]] = set()
    for pair in pair_ids:
        items = tuple(pair)
        if len(items) != 2 or not all(isinstance(x, str) for x in items):
            raise ValueError(f"requested pair must be a (str, str) tuple, got {pair!r}")
        g, h = items
        if g.encode("utf-8") > h.encode("utf-8"):
            raise ValueError(f"requested pair is not canonical (min, max): {pair!r}")
        if items in out:
            raise ValueError(f"duplicate requested pair: {pair!r}")
        out.add(items)
    return out


def _validate_backend_output(
    name: str,
    raw: object,
    requested: set[tuple[str, str]],
    response_dim: int,
) -> dict[tuple[str, str], np.ndarray]:
    """Validate backend output against the requested pair IDs and dimension.

    Parameters
    ----------
    name : str
        Adapter name for error messages.
    raw : object
        The backend's return value; must be a mapping from canonical pair ID to
        a length-``response_dim`` numeric vector.
    requested : set of tuple of str
        The exact set of canonical pair IDs that were requested.
    response_dim : int
        The required length of every prediction vector.

    Returns
    -------
    dict
        A validated, copied mapping with float ``numpy`` arrays.

    Raises
    ------
    ValueError
        For non-mapping output, extra keys, missing keys, non-canonical keys,
        wrong response dimension, or non-finite values.
    """
    if not isinstance(raw, Mapping):
        raise ValueError(f"{name} backend must return a mapping, got {type(raw).__name__}")

    keys = set()
    for key in raw:
        items = tuple(key) if isinstance(key, tuple) else key
        if (
            not isinstance(items, tuple)
            or len(items) != 2
            or not all(isinstance(x, str) for x in items)
        ):
            raise ValueError(f"{name} backend returned a non-pair key: {key!r}")
        keys.add(items)

    extra = keys - requested
    if extra:
        raise ValueError(f"{name} backend returned predictions for unrequested pairs: {extra}")
    missing = requested - keys
    if missing:
        raise ValueError(f"{name} backend is missing predictions for pairs: {missing}")

    out: dict[tuple[str, str], np.ndarray] = {}
    for pair, vec in raw.items():
        arr = np.asarray(vec, dtype=float)
        if arr.shape != (response_dim,):
            raise ValueError(
                f"{name} backend prediction for {pair!r} has shape {arr.shape}, "
                f"expected ({response_dim},)"
            )
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"{name} backend prediction for {pair!r} contains non-finite values")
        out[tuple(pair)] = arr
    return out
