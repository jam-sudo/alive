"""Per-perturbation ESM-2 protein embedding feature bank with base-train standardization.

This module implements the external perturbation feature bank used by the ALIVE
CARTOGRAPHER Trust-Gate MVP.  For each CRISPRi target gene, it stores a fixed-
dimension protein embedding (mean-pooled over residues from ESM-2 ``t33_650M_UR50D``).

Design constraints
------------------
- **Outcome-independence:** No expression or response value enters feature
  construction or standardization.  Only gene→sequence mappings and encoder
  outputs are used.
- **Lazy imports:** ``torch``, ``transformers``, and ``fair-esm`` are in the
  optional ``features`` dependency group.  They are NEVER imported at module
  import time.  The :class:`Esm2Encoder` lazy-imports them inside its methods.
  All CI paths use :class:`MockSequenceEncoder` (numpy-only).
- **Determinism:** Identical (mapping, encoder, pooling, standardize_on) inputs
  produce an identical :class:`FeatureBank` with an identical checksum.
- **Base-train-only standardization:** Per-dimension mean and std are fitted
  exclusively on the ``standardize_on`` (base_train) gene subset, then applied
  to ALL genes.  Zero-std dimensions are guarded with scale=1.0.

Public API
----------
FeatureError
    Raised for absent genes, non-finite vectors, or unfitted standardizers.
SequenceEncoder (Protocol)
    Interface that :class:`MockSequenceEncoder` and :class:`Esm2Encoder` implement.
MockSequenceEncoder
    Deterministic numpy-only encoder for CI use.
Esm2Encoder
    Real ESM-2 encoder for A100 use (lazy torch/esm imports).
FeatureBankProvenance
    Frozen dataclass recording all inputs that produced the bank.
FeatureBank
    The feature bank itself: raw vectors, standardized vectors, metadata, I/O.
build_feature_bank(gene_sequences, encoder, *, sequence_source, ...)
    Builder function that encodes, pools, validates, and standardizes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from alive.provenance import sha256_bytes, sha256_json

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FeatureError(ValueError):
    """Raised for absent genes, non-finite feature vectors, or unfitted standardizers.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Encoder protocol and implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class SequenceEncoder(Protocol):
    """Protocol implemented by all sequence encoders.

    Parameters
    ----------
    dim : int
        Embedding dimension (read-only property).
    model_revision : str
        Pinned model identifier recorded in provenance.

    Methods
    -------
    encode_residues(sequences)
        Return one per-residue array ``(L_i, dim)`` per input sequence.
    """

    @property
    def dim(self) -> int:
        """Embedding dimension."""
        ...

    @property
    def model_revision(self) -> str:
        """Pinned model identifier (recorded in provenance)."""
        ...

    def encode_residues(self, sequences: Sequence[str]) -> list[np.ndarray]:
        """Encode a batch of sequences into per-residue embeddings.

        Parameters
        ----------
        sequences : Sequence[str]
            Protein sequences (single-letter amino acid codes).

        Returns
        -------
        list[np.ndarray]
            One array of shape ``(L_i, dim)`` per input sequence, where
            ``L_i`` is the number of residues in sequence *i*.
        """
        ...


class MockSequenceEncoder:
    """Deterministic, numpy-only sequence encoder for CI.

    Produces per-residue embeddings from a pure arithmetic function of each
    residue's character code and its position index.  For residue at position
    *p* with character *char* in dimension *d*, the value is::

        sin(ord(char) * (p + 1) * (d + 1)) * cos(p + d + 2)

    No RNG state is used.  Identical sequences produce identical arrays on
    every call, across processes, and across Python versions.

    Parameters
    ----------
    dim : int, optional
        Embedding dimension.  Default is 8.
    model_revision : str, optional
        Revision string recorded in provenance.  Default is ``"mock-v1"``.
    """

    def __init__(self, dim: int = 8, model_revision: str = "mock-v1") -> None:
        self._dim = dim
        self._model_revision = model_revision

    @property
    def dim(self) -> int:
        """Embedding dimension."""
        return self._dim

    @property
    def model_revision(self) -> str:
        """Revision string."""
        return self._model_revision

    def encode_residues(self, sequences: Sequence[str]) -> list[np.ndarray]:
        """Encode sequences deterministically using per-residue arithmetic.

        For each sequence, produces an ``(L, dim)`` float64 array from a
        stable seed derived from the sequence content: each residue's value
        at position *p* in dimension *d* is computed as::

            sin(ord(char) * (p + 1) * (d + 1)) * cos((p + d + 2))

        This is fully deterministic, numpy-only, and requires no RNG state.

        Parameters
        ----------
        sequences : Sequence[str]
            Protein sequences.

        Returns
        -------
        list[np.ndarray]
            One ``(L_i, dim)`` array per sequence.
        """
        results: list[np.ndarray] = []
        for seq in sequences:
            L = len(seq)
            arr = np.empty((L, self._dim), dtype=np.float64)
            for p, char in enumerate(seq):
                for d in range(self._dim):
                    arr[p, d] = np.sin(ord(char) * (p + 1) * (d + 1)) * np.cos(p + d + 2)
            results.append(arr)
        return results


# ---------------------------------------------------------------------------
# ESM-2 architecture constants (not configurable: intrinsic to model design)
# ---------------------------------------------------------------------------

#: Embedding dimension for each known ESM-2 model variant.
#: Source: ESM-2 architecture — ``embed_dim`` attribute of the loaded model.
_ESM2_DIM_MAP: dict[str, int] = {
    "esm2_t33_650M_UR50D": 1280,
}


# ---------------------------------------------------------------------------
# Pure helper functions for length policy and length-bucketed batching
# ---------------------------------------------------------------------------


def _apply_length_policy(
    sequences: Sequence[str],
    max_residues: int,
    policy: str,
) -> list[str]:
    """Apply a length policy to each sequence, returning a (possibly truncated) list.

    For each sequence whose length exceeds *max_residues*, the policy is applied:

    - ``"error"``: raise :class:`FeatureError` naming the sequence index and length.
    - ``"truncate"``: silently truncate to the first *max_residues* residues.

    Sequences within the limit are returned unchanged.  Order is preserved.

    Parameters
    ----------
    sequences : Sequence[str]
        Input protein sequences.
    max_residues : int
        Maximum allowed residue count per sequence.
    policy : str
        One of ``"error"`` or ``"truncate"``.

    Returns
    -------
    list[str]
        Processed sequences in the same order as *sequences*.

    Raises
    ------
    FeatureError
        If *policy* is ``"error"`` and any sequence exceeds *max_residues*.
    """
    out: list[str] = []
    for idx, seq in enumerate(sequences):
        if len(seq) > max_residues:
            if policy == "error":
                raise FeatureError(
                    f"Sequence at index {idx} has {len(seq)} residues, which exceeds "
                    f"max_residues={max_residues}. Set long_sequence_policy='truncate' "
                    "to truncate instead."
                )
            # policy == "truncate"
            out.append(seq[:max_residues])
        else:
            out.append(seq)
    return out


def _bucket_indices(
    lengths: Sequence[int],
    max_batch_tokens: int,
    *,
    per_seq_overhead: int = 2,
) -> list[list[int]]:
    """Partition sequence indices into padding-aware length-bucketed mini-batches.

    Sequences are sorted by length descending (stable) so that the first sequence
    added to a batch determines the padded length of the whole batch.  Greedy
    packing: a new sequence is added to the current batch iff the padded cost
    after adding it stays within *max_batch_tokens*::

        padded_cost = (count + 1) * (batch_max_len + per_seq_overhead)

    When the budget would be exceeded, the current batch is closed and a new
    batch is started with the current sequence.

    Parameters
    ----------
    lengths : Sequence[int]
        Residue lengths of the sequences (0-indexed, matching the input order).
    max_batch_tokens : int
        Maximum padded token budget per batch.  The config validation guarantees
        ``max_batch_tokens >= max_residues + per_seq_overhead``, ensuring that a
        single maximum-length sequence always fits in one batch.
    per_seq_overhead : int, optional
        Extra tokens per sequence (BOS + EOS for ESM-2).  Default is 2.

    Returns
    -------
    list[list[int]]
        A list of buckets, each bucket being a list of ORIGINAL sequence indices
        (0-indexed, matching *lengths*).  Together, all buckets cover every index
        exactly once.  Bucket order is determined by the greedy descending-sort
        packing; within each bucket the indices appear in the order they were
        packed (longest first).
    """
    # Sort indices by length DESCENDING (stable: equal-length seqs keep insertion order).
    sorted_indices = sorted(range(len(lengths)), key=lambda i: lengths[i], reverse=True)

    buckets: list[list[int]] = []
    current_bucket: list[int] = []
    current_max_len: int = 0

    for idx in sorted_indices:
        seq_len = lengths[idx]
        candidate_max = max(current_max_len, seq_len)
        candidate_cost = (len(current_bucket) + 1) * (candidate_max + per_seq_overhead)

        if current_bucket and candidate_cost > max_batch_tokens:
            # Close current batch and start a new one.
            buckets.append(current_bucket)
            current_bucket = [idx]
            current_max_len = seq_len
        else:
            current_bucket.append(idx)
            current_max_len = candidate_max

    if current_bucket:
        buckets.append(current_bucket)

    return buckets


# ---------------------------------------------------------------------------
# Esm2Encoder
# ---------------------------------------------------------------------------


class Esm2Encoder:
    """ESM-2 protein language model encoder for use on the A100.

    Lazy-imports ``torch`` and ``esm`` only on the first call to
    :meth:`_forward_bucket` (not in ``__init__``), so that importing this
    module — or constructing the encoder — never triggers a GPU/library load.
    This class must NOT be used in CI (torch and fair-esm are in the optional
    ``features`` dependency group and are not installed in the CI environment).

    The :meth:`dim` and :meth:`model_revision` properties are available
    **without torch** for the pinned default model (``esm2_t33_650M_UR50D``)
    via a built-in dimension map.  For unknown model names, ``dim`` raises
    :class:`FeatureError` until the model is loaded.

    Usage (A100 only)
    -----------------
    ::

        from alive.data.features import Esm2Encoder
        encoder = Esm2Encoder()          # no model load here
        bank = build_feature_bank(mapping, encoder, sequence_source="uniprot-2024-01")

    Parameters
    ----------
    model_name : str, optional
        ESM-2 model identifier.  Defaults to ``"esm2_t33_650M_UR50D"``
        (650 M parameters, 1280-dimensional embeddings).
    max_residues : int, optional
        Maximum residues per sequence.  Sequences exceeding this limit are
        handled per *long_sequence_policy*.  Default is 1022 (ESM-2 t33
        context of 1024 tokens minus BOS and EOS).
    long_sequence_policy : str, optional
        Action when a sequence exceeds *max_residues*: ``"error"`` (raise
        :class:`FeatureError`) or ``"truncate"`` (truncate silently).
        Default is ``"error"``.
    max_batch_tokens : int, optional
        Padded token budget per mini-batch.  A100-tunable.  Default is 16384.

    Notes
    -----
    This encoder requires A100-class hardware for practical throughput.
    The full ``t33_650M_UR50D`` model has 33 transformer layers and produces
    1280-dimensional residue embeddings (layer 33 representations, with BOS
    and EOS tokens stripped).

    The ``esm2_t33_650M_UR50D`` embedding dimension (1280) is documented as
    an architecture constant in :data:`_ESM2_DIM_MAP`; it is NOT a
    configurable parameter.
    """

    def __init__(
        self,
        model_name: str = "esm2_t33_650M_UR50D",
        *,
        max_residues: int = 1022,
        long_sequence_policy: str = "error",
        max_batch_tokens: int = 16384,
    ) -> None:
        # Defensive validation (config-driven callers are also validated by
        # load_config; this guards direct construction so a too-small budget can
        # never silently build an over-budget singleton bucket).
        if max_residues < 1:
            raise FeatureError(f"max_residues must be >= 1, got {max_residues}.")
        if long_sequence_policy not in ("error", "truncate"):
            raise FeatureError(
                f"long_sequence_policy must be 'error' or 'truncate', got {long_sequence_policy!r}."
            )
        if max_batch_tokens < max_residues + 2:
            raise FeatureError(
                f"max_batch_tokens ({max_batch_tokens}) must be >= max_residues + 2 "
                f"({max_residues + 2}) so a single max-length sequence always fits one batch."
            )
        # Store config ONLY — no torch import, no model load.
        self._model_name = model_name
        self._max_residues = max_residues
        self._long_sequence_policy = long_sequence_policy
        self._max_batch_tokens = max_batch_tokens

        # Dimension from the built-in map; None if unknown (deferred to model load).
        self._dim: int | None = _ESM2_DIM_MAP.get(model_name)

        # Lazy model state — populated on first call to _ensure_model().
        self._model = None
        self._alphabet = None
        self._batch_converter = None

    # ------------------------------------------------------------------
    # Properties (work WITHOUT torch for pinned model names)
    # ------------------------------------------------------------------

    @property
    def dim(self) -> int:
        """Embedding dimension.

        Returns 1280 for ``esm2_t33_650M_UR50D`` without requiring torch.
        For unknown model names, raises :class:`FeatureError` until the model
        has been loaded by a call to :meth:`encode_residues`.
        """
        if self._dim is None:
            raise FeatureError(
                f"Embedding dimension for model {self._model_name!r} is not known at "
                "construction time. Call encode_residues() to load the model and resolve dim."
            )
        return self._dim

    @property
    def model_revision(self) -> str:
        """Pinned ESM-2 model identifier (no torch required)."""
        return self._model_name

    # ------------------------------------------------------------------
    # Torch-only leaf: model loading + forward pass
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        """Load the ESM-2 model lazily on the first call (torch-only)."""
        if self._model is not None:
            return

        import esm  # type: ignore[import]  # noqa: PLC0415
        import torch  # type: ignore[import]  # noqa: PLC0415

        model, alphabet = esm.pretrained.load_model_and_alphabet(self._model_name)
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()

        self._model = model
        self._alphabet = alphabet
        self._batch_converter = alphabet.get_batch_converter()

        # Resolve dim from the loaded model if it was unknown at init.
        if self._dim is None:
            self._dim = model.embed_dim

    def _forward_bucket(self, sequences: Sequence[str]) -> list[np.ndarray]:
        """Run one mini-batch forward pass through the ESM-2 model.

        This is the TORCH-ONLY leaf.  It is never called in CI (torch absent).
        GPU memory is freed after each call.

        Parameters
        ----------
        sequences : Sequence[str]
            A mini-batch of protein sequences (after length policy has been
            applied).  All sequences fit within the token budget for this batch.

        Returns
        -------
        list[np.ndarray]
            One ``(L_i, dim)`` float32 array per input sequence, in the same
            order as *sequences*.
        """
        import torch  # type: ignore[import]  # noqa: PLC0415

        self._ensure_model()

        data = [(f"seq_{i}", seq) for i, seq in enumerate(sequences)]
        _, _, tokens = self._batch_converter(data)
        if torch.cuda.is_available():
            tokens = tokens.cuda()

        n_layers = self._model.num_layers
        with torch.no_grad():
            results = self._model(tokens, repr_layers=[n_layers], return_contacts=False)

        token_reps = results["representations"][n_layers]  # (B, L+2, dim)
        # Strip BOS (index 0) and EOS (index -1) tokens.
        output: list[np.ndarray] = []
        for i, seq in enumerate(sequences):
            rep = token_reps[i, 1 : len(seq) + 1, :]  # (L_i, dim)
            output.append(rep.cpu().numpy().astype(np.float32))

        # Free GPU memory eagerly after each bucket.
        del tokens, results, token_reps
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return output

    # ------------------------------------------------------------------
    # Public orchestration method
    # ------------------------------------------------------------------

    def encode_residues(self, sequences: Sequence[str]) -> list[np.ndarray]:
        """Encode protein sequences into per-residue ESM-2 embeddings.

        Applies the length policy, partitions sequences into padding-aware
        mini-batches, runs each batch through the model, and reassembles
        the results in INPUT ORDER.

        Parameters
        ----------
        sequences : Sequence[str]
            Protein sequences (single-letter amino acid codes).

        Returns
        -------
        list[np.ndarray]
            One ``(L_i, dim)`` float32 array per input sequence, where
            ``L_i`` is the number of residues in the (potentially truncated)
            sequence *i*.  Output is in the same order as the input.

        Raises
        ------
        FeatureError
            If *long_sequence_policy* is ``"error"`` and any sequence
            exceeds *max_residues*.
        """
        # 1. Apply length policy (pure; no torch).
        prepared = _apply_length_policy(sequences, self._max_residues, self._long_sequence_policy)

        # 2. Compute length-bucketed mini-batch indices (pure; no torch).
        lengths = [len(s) for s in prepared]
        buckets = _bucket_indices(lengths, self._max_batch_tokens)

        # 3. Allocate result list in original-input order.
        results_by_index: list[np.ndarray | None] = [None] * len(prepared)

        # 4. Run each bucket through the torch-only forward leaf.
        for bucket in buckets:
            bucket_seqs = [prepared[i] for i in bucket]
            bucket_results = self._forward_bucket(bucket_seqs)
            for original_idx, arr in zip(bucket, bucket_results):
                results_by_index[original_idx] = arr

        # 5. Return in INPUT order (None slots are a programming error).
        return [r for r in results_by_index if r is not None]


# ---------------------------------------------------------------------------
# FeatureBankProvenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureBankProvenance:
    """Immutable provenance record for a :class:`FeatureBank`.

    Parameters
    ----------
    model_revision : str
        Encoder revision string (e.g. ``"esm2_t33_650M_UR50D"``).
    sequence_source : str
        Versioned mapping identifier (e.g. ``"uniprot-2024-01"``).
    pooling : str
        Pooling strategy used (currently always ``"mean"``).
    dim : int
        Embedding dimension.
    dtype : str
        NumPy dtype string of stored vectors (e.g. ``"float32"``).
    n_genes : int
        Number of usable (non-excluded) genes.
    mapping_sha256 : str
        SHA-256 of a canonical serialisation of the gene→sequence mapping.
    features_sha256 : str
        SHA-256 of the raw feature matrix bytes.
    """

    model_revision: str
    sequence_source: str
    pooling: str
    dim: int
    dtype: str
    n_genes: int
    mapping_sha256: str
    features_sha256: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of provenance fields."""
        return {
            "model_revision": self.model_revision,
            "sequence_source": self.sequence_source,
            "pooling": self.pooling,
            "dim": self.dim,
            "dtype": self.dtype,
            "n_genes": self.n_genes,
            "mapping_sha256": self.mapping_sha256,
            "features_sha256": self.features_sha256,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureBankProvenance":
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            model_revision=d["model_revision"],
            sequence_source=d["sequence_source"],
            pooling=d["pooling"],
            dim=d["dim"],
            dtype=d["dtype"],
            n_genes=d["n_genes"],
            mapping_sha256=d["mapping_sha256"],
            features_sha256=d["features_sha256"],
        )


# ---------------------------------------------------------------------------
# FeatureBank
# ---------------------------------------------------------------------------


class FeatureBank:
    """Per-perturbation feature bank with optional base-train standardization.

    Do not construct directly; use :func:`build_feature_bank` or
    :meth:`read`.

    Attributes
    ----------
    genes : tuple[str, ...]
        Usable gene IDs, sorted lexicographically.
    dim : int
        Embedding dimension.
    excluded : dict[str, str]
        Genes excluded from the bank, mapping gene ID → reason string
        (``"missing sequence"`` or ``"ambiguous mapping"``).
    provenance : FeatureBankProvenance
        Frozen provenance record.
    """

    def __init__(
        self,
        genes: tuple[str, ...],
        raw_matrix: np.ndarray,
        excluded: dict[str, str],
        provenance: FeatureBankProvenance,
        std_mean: np.ndarray | None = None,
        std_scale: np.ndarray | None = None,
    ) -> None:
        self.genes = genes
        self.dim = provenance.dim
        self.excluded = excluded
        self.provenance = provenance
        self._raw_matrix = raw_matrix  # (n_genes, dim), rows in `genes` order
        self._gene_index: dict[str, int] = {g: i for i, g in enumerate(genes)}
        self._std_mean = std_mean  # (dim,) or None
        self._std_scale = std_scale  # (dim,) or None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def has(self, gene: str) -> bool:
        """Return True if *gene* is in the bank (not excluded).

        Parameters
        ----------
        gene : str
            Gene identifier.

        Returns
        -------
        bool
        """
        return gene in self._gene_index

    def vector(self, gene: str) -> np.ndarray:
        """Return the raw pooled embedding vector for *gene*.

        Parameters
        ----------
        gene : str
            Gene identifier.

        Returns
        -------
        np.ndarray
            1-D array of shape ``(dim,)``.

        Raises
        ------
        FeatureError
            If *gene* is not in the bank.
        """
        if gene not in self._gene_index:
            raise FeatureError(
                f"Gene {gene!r} is not in the feature bank. "
                "It may have been excluded (missing or ambiguous sequence)."
            )
        return self._raw_matrix[self._gene_index[gene]]

    def standardized_vector(self, gene: str) -> np.ndarray:
        """Return the standardized embedding vector for *gene*.

        Standardization parameters are fitted on the ``base_train`` subset
        passed to :func:`build_feature_bank` and applied to ALL genes.

        Parameters
        ----------
        gene : str
            Gene identifier.

        Returns
        -------
        np.ndarray
            1-D array of shape ``(dim,)``.

        Raises
        ------
        FeatureError
            If the standardizer has not been fitted (``standardize_on=None``
            was passed to :func:`build_feature_bank`) or if *gene* is absent.
        """
        if self._std_mean is None or self._std_scale is None:
            raise FeatureError(
                "standardizer not fitted: pass a non-None standardize_on to build_feature_bank."
            )
        raw = self.vector(gene)  # raises FeatureError if absent
        return (raw - self._std_mean) / self._std_scale

    def matrix(self, genes: Sequence[str] | None = None) -> np.ndarray:
        """Return a raw feature matrix with one row per gene.

        Parameters
        ----------
        genes : Sequence[str] or None, optional
            Ordered list of gene IDs.  If ``None``, uses :attr:`genes`
            (sorted order).

        Returns
        -------
        np.ndarray
            2-D array of shape ``(n_genes, dim)``.
        """
        order = genes if genes is not None else self.genes
        return np.stack([self.vector(g) for g in order], axis=0)

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------

    @cached_property
    def checksum(self) -> str:
        """Stable SHA-256 over provenance + sorted genes + standardizer state.

        Returns
        -------
        str
            Lowercase hex-encoded SHA-256 digest.
        """
        std_state: dict = {}
        if self._std_mean is not None:
            std_state["mean"] = self._std_mean.tolist()
        if self._std_scale is not None:
            std_state["scale"] = self._std_scale.tolist()

        payload = {
            "provenance": self.provenance.to_dict(),
            "genes": list(self.genes),
            "excluded": dict(sorted(self.excluded.items())),
            "standardizer": std_state,
        }
        return sha256_json(payload)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def write(self, path: str | Path) -> None:
        """Write the feature bank to disk.

        Writes two files:

        - ``{path}.npz`` — compressed numpy archive containing the raw
          feature matrix and optional standardizer arrays.
        - ``{path}.json`` — metadata (provenance, gene list, excluded map,
          checksum).

        Parameters
        ----------
        path : str or Path
            Base path (without extension).  Parent directory must exist.
        """
        path = Path(path)
        arrays: dict[str, np.ndarray] = {"features": self._raw_matrix}
        if self._std_mean is not None:
            arrays["std_mean"] = self._std_mean
        if self._std_scale is not None:
            arrays["std_scale"] = self._std_scale
        np.savez_compressed(str(path) + ".npz", **arrays)

        meta = {
            "genes": list(self.genes),
            "excluded": self.excluded,
            "provenance": self.provenance.to_dict(),
            "checksum": self.checksum,
        }
        path.with_suffix(".json").write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: str | Path) -> "FeatureBank":
        """Reconstruct a :class:`FeatureBank` from files written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Base path (without extension) as passed to :meth:`write`.

        Returns
        -------
        FeatureBank
        """
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        npz = np.load(str(path) + ".npz")

        genes = tuple(meta["genes"])
        excluded = dict(meta["excluded"])
        provenance = FeatureBankProvenance.from_dict(meta["provenance"])
        raw_matrix = npz["features"]

        std_mean = npz["std_mean"] if "std_mean" in npz else None
        std_scale = npz["std_scale"] if "std_scale" in npz else None

        return cls(
            genes=genes,
            raw_matrix=raw_matrix,
            excluded=excluded,
            provenance=provenance,
            std_mean=std_mean,
            std_scale=std_scale,
        )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_feature_bank(
    gene_sequences: Mapping[str, Sequence[str]],
    encoder: SequenceEncoder,
    *,
    sequence_source: str,
    standardize_on: Sequence[str] | None = None,
    pooling: str = "mean",
    dtype: str = "float32",
) -> FeatureBank:
    """Build a :class:`FeatureBank` from a gene→sequence mapping and an encoder.

    Parameters
    ----------
    gene_sequences : Mapping[str, Sequence[str]]
        Mapping from gene ID to a list of candidate protein sequences.
        Exactly one candidate → usable; zero → excluded (missing sequence);
        more than one → excluded (ambiguous mapping).
    encoder : SequenceEncoder
        Encoder that converts sequences to per-residue embeddings.
    sequence_source : str
        Versioned mapping identifier recorded in provenance.
    standardize_on : Sequence[str] or None, optional
        Gene IDs of the ``base_train`` split.  The per-dimension mean and
        std are fitted on these genes ONLY, then applied to all genes.
        Genes in *standardize_on* that are not usable are silently ignored.
        If ``None``, :meth:`FeatureBank.standardized_vector` will raise.
    pooling : str, optional
        Pooling strategy.  Currently only ``"mean"`` is supported.
    dtype : str, optional
        NumPy dtype for stored vectors (e.g. ``"float32"``).

    Returns
    -------
    FeatureBank

    Raises
    ------
    FeatureError
        If any usable gene produces a non-finite pooled vector, or if an
        unsupported pooling strategy is specified.
    ValueError
        If *pooling* is not ``"mean"``.
    """
    if pooling != "mean":
        raise ValueError(f"Unsupported pooling strategy: {pooling!r}. Only 'mean' is supported.")

    # ------------------------------------------------------------------
    # 1. Classify genes: usable vs excluded
    # ------------------------------------------------------------------
    excluded: dict[str, str] = {}
    usable_genes: list[str] = []
    usable_seqs: list[str] = []

    for gene, candidates in gene_sequences.items():
        n = len(candidates)
        if n == 0:
            excluded[gene] = "missing sequence"
        elif n > 1:
            excluded[gene] = "ambiguous mapping"
        else:
            usable_genes.append(gene)
            usable_seqs.append(candidates[0])

    # ------------------------------------------------------------------
    # 2. Encode and pool
    # ------------------------------------------------------------------
    np_dtype = np.dtype(dtype)

    raw_vectors: dict[str, np.ndarray] = {}
    if usable_genes:
        per_residue_list = encoder.encode_residues(usable_seqs)
        for gene, per_residue in zip(usable_genes, per_residue_list):
            if pooling == "mean":
                pooled = per_residue.mean(axis=0)

            # Validate dimension
            if pooled.shape != (encoder.dim,):
                raise FeatureError(
                    f"Gene {gene!r}: pooled vector has shape {pooled.shape}, "
                    f"expected ({encoder.dim},)."
                )
            # Validate finite
            if not np.all(np.isfinite(pooled)):
                raise FeatureError(
                    f"Gene {gene!r}: pooled vector contains non-finite values "
                    "(inf or nan). Check the encoder output."
                )
            raw_vectors[gene] = pooled.astype(np_dtype)

    # ------------------------------------------------------------------
    # 3. Sort genes and build matrix
    # ------------------------------------------------------------------
    sorted_genes: tuple[str, ...] = tuple(sorted(raw_vectors.keys()))
    if sorted_genes:
        raw_matrix = np.stack([raw_vectors[g] for g in sorted_genes], axis=0)
    else:
        raw_matrix = np.empty((0, encoder.dim), dtype=np_dtype)

    # ------------------------------------------------------------------
    # 4. Provenance
    # ------------------------------------------------------------------
    # Canonical representation of gene_sequences for hashing: sorted dict
    # of (gene -> sorted list of sequences).
    canonical_mapping = {gene: sorted(list(seqs)) for gene, seqs in sorted(gene_sequences.items())}
    mapping_sha256 = sha256_json(canonical_mapping)
    features_sha256 = sha256_bytes(raw_matrix.tobytes())

    provenance = FeatureBankProvenance(
        model_revision=encoder.model_revision,
        sequence_source=sequence_source,
        pooling=pooling,
        dim=encoder.dim,
        dtype=str(np_dtype),
        n_genes=len(sorted_genes),
        mapping_sha256=mapping_sha256,
        features_sha256=features_sha256,
    )

    # ------------------------------------------------------------------
    # 5. Standardization (base_train-only fit, apply to all)
    # ------------------------------------------------------------------
    std_mean: np.ndarray | None = None
    std_scale: np.ndarray | None = None

    if standardize_on is not None:
        # Intersect with usable genes
        fit_genes = [g for g in standardize_on if g in raw_vectors]
        if fit_genes:
            fit_matrix = np.stack([raw_vectors[g] for g in fit_genes], axis=0).astype(np.float64)
            bt_mean = fit_matrix.mean(axis=0)
            bt_std = fit_matrix.std(axis=0, ddof=1) if len(fit_genes) > 1 else np.zeros(encoder.dim)
            bt_scale = np.where(bt_std == 0, 1.0, bt_std)
            std_mean = bt_mean.astype(np_dtype)
            std_scale = bt_scale.astype(np_dtype)
        else:
            # No usable base_train genes: fit on empty → mean=0, scale=1
            std_mean = np.zeros(encoder.dim, dtype=np_dtype)
            std_scale = np.ones(encoder.dim, dtype=np_dtype)

    return FeatureBank(
        genes=sorted_genes,
        raw_matrix=raw_matrix,
        excluded=excluded,
        provenance=provenance,
        std_mean=std_mean,
        std_scale=std_scale,
    )
