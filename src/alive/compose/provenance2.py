"""COMPLETE Phase-2b composite provenance and run identity (Task 2b-6).

COMPOSE-K562-v1 Phase 2b opens the COMPOSE seal exactly once. This module is the
COMPLETE composite provenance + run-identity assembly the orchestrator (Task 8)
and the terminal writer (Task 7) consume around that single opening. It

  1. recomputes the composite COMPOSE ``run_id`` (one canonical definition,
     :func:`recompute_run_id`), binding config + data-card + raw/source +
     sequence-mapping so the same config on different data yields a different id;
  2. bundles the COMPLETE provenance set the brief lists into a frozen,
     self-checksummed :class:`Phase2bProvenance` record;
  3. records that set into a write-once :class:`~alive.provenance.RunLedger`
     under canonical artifact names (:func:`record_phase2b_provenance`);
  4. ABORTS BEFORE seal access on any upstream absence / mismatch
     (:func:`verify_upstream_before_access` raises :class:`ProvenanceError`; the
     seal stays CLOSED); and
  5. flags post-access inconsistencies as :class:`PostAccessStatus.INVALID`
     WITHOUT raising (:func:`check_post_access_consistency`; the seal is already
     consumed, so the terminal writer records a terminal artifact rather than
     crashing).

The CRITICAL distinction (CLAUDE.md §6 multiple-seal rule, §11 write-once
provenance) is the two-path split implemented as two distinct functions:

  * a mismatch / absence detectable BEFORE access RAISES — abort, seal closed;
  * a mismatch detectable only AFTER access returns ``INVALID`` — the seal is
    already burned, so we must NOT raise into a crash; we return an INVALID
    signal so the terminal writer (Task 7) records a terminal artifact.

Layering (intentional, not duplication): Task-2 preflight
(:mod:`alive.compose.preflight`) does a FOCUSED inline bundle-checksum + run-id
check on the outcome-free inputs. This module is the COMPLETE composite
assembly plus the pre/post-access split; it does not modify preflight.

This module's run identity is independent of TG-K562 (CLAUDE.md §6.3): a COMPOSE
run id, audit file or result can never represent a CARTOGRAPHER seal, and vice
versa. SYNTHETIC-ONLY: this is code only — it touches no seal, no outcome
store and no real Norman data.

Public API
----------
ProvenanceError
    PRE-ACCESS abort type: raised to leave the seal closed.
PostAccessStatus
    POST-ACCESS result enum (``OK`` / ``INVALID``); the post-access path returns
    this and never raises on a detected inconsistency.
Phase2bProvenance
    Frozen, self-checksummed COMPLETE provenance record.
recompute_run_id(...)
    Canonical composite COMPOSE ``run_id`` (thin wrapper over
    :func:`alive.compose.datacard.compute_compose_run_id`).
record_phase2b_provenance(...)
    Assemble the COMPLETE provenance into a write-once :class:`RunLedger`.
verify_upstream_before_access(...)
    PRE-ACCESS gate: abort (raise) on a wrong run id, an absent or mismatched
    upstream artifact, or an empty required set.
check_post_access_consistency(...)
    POST-ACCESS path: return ``OK`` / ``INVALID`` (never raise on a mismatch).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from pathlib import Path

from alive.compose.datacard import compute_compose_run_id
from alive.io import atomic_write_once
from alive.provenance import (
    DuplicateArtifactError,
    EnvironmentInfo,
    LedgerError,
    RunLedger,
    sha256_json,
)

#: The active COMPOSE protocol this provenance binds to.
PROTOCOL = "COMPOSE-K562-v1"


class ProvenanceError(ValueError):
    """PRE-ACCESS abort: a provenance mismatch / absence detectable BEFORE access.

    Raised by :func:`verify_upstream_before_access` (and wrapping a write-once
    conflict in :func:`record_phase2b_provenance`). When this is raised before
    the seal opener runs, the seal stays CLOSED — the run aborts with zero
    sealed access. It is deliberately distinct from
    :class:`alive.provenance.LedgerError` and the post-access ``INVALID`` signal
    so the two paths can never be confused.

    Parameters
    ----------
    message : str
        Human-readable description of the abort reason.
    """


class PostAccessStatus(Enum):
    """POST-ACCESS consistency status.

    Returned by :func:`check_post_access_consistency`. The seal is already
    consumed by the time this is evaluated, so a detected inconsistency must NOT
    raise — it is reported as ``INVALID`` so the terminal writer (Task 7) records
    a terminal artifact instead of crashing.
    """

    OK = "OK"
    INVALID = "INVALID"


def recompute_run_id(
    *,
    config_digest: str,
    data_card_digest: str,
    raw_or_source_sha256: str,
    sequence_mapping_sha256: str,
    length: int = 16,
) -> str:
    """Recompute the canonical composite COMPOSE ``run_id`` for Phase 2b.

    The single run-identity definition for Phase 2b: a thin canonical wrapper
    over :func:`alive.compose.datacard.compute_compose_run_id` so there is ONE
    place that binds config + data-card + raw/source + sequence-mapping. The same
    config on different data yields a different ``run_id`` (CLAUDE.md §11), and
    the identity stays independent of TG-K562 (§6.3).

    Parameters
    ----------
    config_digest : str
        Deterministic digest of the resolved config
        (``ComposePhase2Config.config_sha256``).
    data_card_digest : str
        Canonical-JSON SHA-256 of the validated Norman data-card.
    raw_or_source_sha256 : str
        The raw-or-source digest (``data_card["raw_or_source"]["digest"]``).
    sequence_mapping_sha256 : str
        Canonical digest of the gene→protein-sequence mapping.
    length : int, optional
        Number of leading hex characters to return. Defaults to 16.

    Returns
    -------
    str
        ``length``-character lowercase hexadecimal run identifier.
    """
    return compute_compose_run_id(
        config_digest=config_digest,
        data_card_digest=data_card_digest,
        raw_or_source_digest=raw_or_source_sha256,
        sequence_mapping_digest=sequence_mapping_sha256,
        length=length,
    )


#: Fields knowable only AFTER the single sealed opening; excluded from the
#: pre-access digest subset (Change C). Fixed set — do not extend.
_POST_ACCESS_FIELDS: tuple[str, ...] = (
    "regime_result_double_sha256",
    "regime_result_single_sha256",
    "terminal_report_sha256",
)


@dataclass(frozen=True)
class Phase2bProvenance:
    """Frozen, self-checksummed COMPLETE Phase-2b provenance record.

    Bundles the COMPLETE provenance set the brief lists (CLAUDE.md §11): the
    active protocol and resolved config digest; the pair and exclusion manifest
    hashes; the data-card, raw/source and processed hashes; the sequence-mapping
    and feature-bank hashes; the response-space and factor artifact hashes; the
    model-lock and frozen-prediction-bundle hashes; the Git SHA and clean-state
    flag; the dependency-lock hash, GEARS/CPA revisions, Python/platform, device
    and precision; the registered seeds; the seal-audit reference; and the
    regime-result and terminal-report checksums.

    :attr:`self_checksum` is the canonical-JSON SHA-256 of :meth:`to_dict` (which
    excludes the checksum itself), so two records built from identical inputs
    have an identical self-checksum and any content change moves it.

    Attributes
    ----------
    protocol : str
        Active protocol name (``"COMPOSE-K562-v1"``).
    config_digest : str
        Deterministic digest of the resolved config.
    pair_manifest_sha256, exclusion_manifest_sha256 : str
        The pair-split manifest and outcome-independent exclusion manifest hashes.
    data_card_sha256, raw_or_source_sha256, processed_sha256 : str
        The validated data-card digest, the raw/source digest, and the processed
        AnnData file digest.
    sequence_mapping_sha256, feature_bank_sha256 : str
        The gene→protein-sequence mapping digest and the frozen feature-bank hash.
    response_space_sha256, factor_bank_sha256 : str
        The response-space and factor-bank artifact hashes.
    model_lock_sha256, frozen_prediction_bundle_sha256 : str
        The frozen model-lock and Phase-2a frozen-prediction-bundle hashes.
    git_commit : str
        Full 40-char SHA-1 of HEAD (or ``"UNKNOWN"``).
    git_clean : bool
        Whether the working tree was a clean, committed Git state.
    dependency_lock_sha256 : str
        SHA-256 of the dependency lockfile (``uv.lock``).
    gears_revision, cpa_revision : str
        Pinned GEARS / CPA baseline revisions.
    python_version, platform : str
        Python version and platform description strings.
    device, precision : str
        Compute device and numerical precision tags.
    registered_seeds : tuple of int
        Registered model seeds.
    split_seed : int
        Registered split seed.
    seal_audit_reference : str
        Reference (path / identifier) to the independent COMPOSE seal audit.
    regime_result_double_sha256, regime_result_single_sha256 : str
        Checksums of the double-unseen and single-unseen regime results.
    terminal_report_sha256 : str
        Checksum of the terminal report artifact.
    """

    protocol: str
    config_digest: str
    pair_manifest_sha256: str
    exclusion_manifest_sha256: str
    data_card_sha256: str
    raw_or_source_sha256: str
    processed_sha256: str
    sequence_mapping_sha256: str
    feature_bank_sha256: str
    response_space_sha256: str
    factor_bank_sha256: str
    model_lock_sha256: str
    frozen_prediction_bundle_sha256: str
    git_commit: str
    git_clean: bool
    dependency_lock_sha256: str
    gears_revision: str
    cpa_revision: str
    python_version: str
    platform: str
    device: str
    precision: str
    registered_seeds: tuple[int, ...]
    split_seed: int
    seal_audit_reference: str
    regime_result_double_sha256: str
    regime_result_single_sha256: str
    terminal_report_sha256: str

    def to_dict(self) -> dict:
        """Serialise the content (EXCLUDING the self-checksum) to a JSON dict.

        Deterministic: identical inputs produce an identical dict. The
        self-checksum is intentionally absent so :attr:`self_checksum` is a hash
        of the content rather than of itself.

        Returns
        -------
        dict
            JSON-serialisable content dict.
        """
        return {
            "protocol": self.protocol,
            "config_digest": self.config_digest,
            "pair_manifest_sha256": self.pair_manifest_sha256,
            "exclusion_manifest_sha256": self.exclusion_manifest_sha256,
            "data_card_sha256": self.data_card_sha256,
            "raw_or_source_sha256": self.raw_or_source_sha256,
            "processed_sha256": self.processed_sha256,
            "sequence_mapping_sha256": self.sequence_mapping_sha256,
            "feature_bank_sha256": self.feature_bank_sha256,
            "response_space_sha256": self.response_space_sha256,
            "factor_bank_sha256": self.factor_bank_sha256,
            "model_lock_sha256": self.model_lock_sha256,
            "frozen_prediction_bundle_sha256": self.frozen_prediction_bundle_sha256,
            "git_commit": self.git_commit,
            "git_clean": bool(self.git_clean),
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "gears_revision": self.gears_revision,
            "cpa_revision": self.cpa_revision,
            "python_version": self.python_version,
            "platform": self.platform,
            "device": self.device,
            "precision": self.precision,
            "registered_seeds": list(self.registered_seeds),
            "split_seed": self.split_seed,
            "seal_audit_reference": self.seal_audit_reference,
            "regime_result_double_sha256": self.regime_result_double_sha256,
            "regime_result_single_sha256": self.regime_result_single_sha256,
            "terminal_report_sha256": self.terminal_report_sha256,
        }

    @cached_property
    def self_checksum(self) -> str:
        """Canonical-JSON SHA-256 of :meth:`to_dict` (excludes the checksum).

        Returns
        -------
        str
            64-character lowercase hex SHA-256 of the content.
        """
        return sha256_json(self.to_dict())

    def pre_access_digest_subset(self) -> dict:
        """Return the pre-access digest subset (``to_dict`` minus post-access fields).

        The subset is everything computable BEFORE the seal opens: it drops the
        regime-result and terminal-report checksums (:data:`_POST_ACCESS_FIELDS`),
        which are known only after the single sealed access. Recording this
        subset's checksum before access (Change C) turns the post-access
        provenance consistency check into a real tamper detector rather than a
        self-reference (CLAUDE.md §11).

        Returns
        -------
        dict
            The content dict with the post-access keys removed.
        """
        subset = self.to_dict()
        for key in _POST_ACCESS_FIELDS:
            subset.pop(key)
        return subset

    @cached_property
    def pre_access_checksum(self) -> str:
        """Canonical-JSON SHA-256 of :meth:`pre_access_digest_subset`.

        Stable across changes to post-access-only fields; moves on any change to
        a pre-access field. This is the value persisted into the write-once
        ledger before seal access and re-checked afterwards (Change C).

        Returns
        -------
        str
            64-character lowercase hex SHA-256 of the pre-access subset.
        """
        return sha256_json(self.pre_access_digest_subset())


#: Canonical write-once artifact name for the pre-access provenance subset
#: checksum (Change C). Recorded BEFORE seal access; re-checked afterwards.
PRE_ACCESS_PROVENANCE_ARTIFACT = "phase2b_pre_access_provenance"

#: Durable write-once snapshot of the ledger immediately before seal access.
PRE_ACCESS_LEDGER_FILENAME = "phase2b_pre_access_ledger.json"

#: Canonical write-once artifact names → the :class:`Phase2bProvenance` field
#: whose value is recorded directly (already a SHA-256 hex digest).
_DIGEST_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("pair_manifest", "pair_manifest_sha256"),
    ("exclusion_manifest", "exclusion_manifest_sha256"),
    ("data_card", "data_card_sha256"),
    ("raw_data", "raw_or_source_sha256"),
    ("processed_data", "processed_sha256"),
    ("sequence_mapping", "sequence_mapping_sha256"),
    ("feature_bank", "feature_bank_sha256"),
    ("response_space", "response_space_sha256"),
    ("factor_bank", "factor_bank_sha256"),
    ("model_lock", "model_lock_sha256"),
    ("frozen_prediction_bundle", "frozen_prediction_bundle_sha256"),
    ("dependency_lock", "dependency_lock_sha256"),
    ("regime_result_double", "regime_result_double_sha256"),
    ("regime_result_single", "regime_result_single_sha256"),
    ("terminal_report", "terminal_report_sha256"),
)

#: Canonical write-once artifact names → the :class:`Phase2bProvenance` field
#: whose *value* is a string/scalar recorded as ``sha256_json(value)`` evidence
#: (revisions, device, precision, seal-audit reference, the clean-state flag).
_EVIDENCE_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("gears_revision", "gears_revision"),
    ("cpa_revision", "cpa_revision"),
    ("device", "device"),
    ("precision", "precision"),
    ("seal_audit", "seal_audit_reference"),
    ("git_clean", "git_clean"),
)


def record_phase2b_provenance(
    provenance: Phase2bProvenance,
    *,
    run_id: str,
    config_sha256: str,
    environment: EnvironmentInfo,
    ledger: RunLedger | None = None,
) -> RunLedger:
    """Assemble the COMPLETE Phase-2b provenance into a write-once ledger.

    Records the COMPLETE provenance set under canonical, write-once artifact
    names (CLAUDE.md §11). Hash-valued fields (manifest / data-card / model /
    bundle / regime-result / terminal-report digests) are recorded directly;
    string/scalar evidence (GEARS/CPA revisions, device, precision, the
    seal-audit reference, the clean-state flag) is recorded as ``sha256_json`` of
    the value so a tamper is detectable. The record's own self-checksum is
    recorded as the ``phase2b_provenance`` artifact. The Git SHA and registered
    seeds are recorded via the :class:`EnvironmentInfo` block of the ledger.

    Write-once: each name is recorded exactly once. Re-recording a CONFLICTING
    value for an already-present name raises (RunLedger raises
    :class:`DuplicateArtifactError` on ANY re-record of a name, even with the
    same value; here that surfaces as :class:`ProvenanceError`). The COMPOSE
    seal/provenance is independent of TG-K562 (§6.3).

    Parameters
    ----------
    provenance : Phase2bProvenance
        The COMPLETE frozen provenance record to assemble.
    run_id : str
        The composite run identifier (from :func:`recompute_run_id`); recorded as
        the ledger's ``run_id``.
    config_sha256 : str
        Deterministic config digest; recorded as the ledger's ``config_sha256``.
    environment : EnvironmentInfo
        Captured runtime environment (Python/platform, git HEAD, lockfile,
        registered seeds).
    ledger : RunLedger or None, optional
        An existing ledger to record into. When ``None`` (the default) a fresh
        ledger is created. A pre-existing artifact name with a conflicting value
        raises (write-once).

    Returns
    -------
    RunLedger
        The write-once ledger carrying the COMPLETE Phase-2b provenance set.

    Raises
    ------
    ProvenanceError
        If recording any canonical artifact name conflicts with an existing
        entry (write-once violation).
    """
    if ledger is None:
        ledger = RunLedger(run_id=run_id, config_sha256=config_sha256, environment=environment)

    def _record(name: str, sha: str) -> None:
        try:
            ledger.record_artifact(name, sha)
        except DuplicateArtifactError as exc:
            raise ProvenanceError(
                f"write-once violation recording Phase-2b provenance artifact {name!r}: {exc}"
            ) from exc

    for name, field in _DIGEST_ARTIFACTS:
        _record(name, getattr(provenance, field))

    for name, field in _EVIDENCE_ARTIFACTS:
        _record(name, sha256_json(getattr(provenance, field)))

    # The record's own self-checksum binds the COMPLETE assembly.
    _record("phase2b_provenance", provenance.self_checksum)

    return ledger


def record_pre_access_provenance(*, ledger: RunLedger, provenance: Phase2bProvenance) -> str:
    """Record the pre-access digest-subset checksum into the ledger BEFORE access.

    Persists :attr:`Phase2bProvenance.pre_access_checksum` under
    :data:`PRE_ACCESS_PROVENANCE_ARTIFACT` in the write-once ledger, so the
    post-access consistency check (Change C) can cross-verify against a PERSISTED
    value rather than the in-memory record (CLAUDE.md §11). Called before the
    seal opens; the seal stays closed if this raises.

    Parameters
    ----------
    ledger : RunLedger
        The write-once run ledger to record into.
    provenance : Phase2bProvenance
        The provenance record whose pre-access subset checksum is persisted.

    Returns
    -------
    str
        The recorded pre-access subset checksum.

    Raises
    ------
    ProvenanceError
        If the artifact name is already recorded (write-once violation).
    """
    checksum = provenance.pre_access_checksum
    try:
        ledger.record_artifact(PRE_ACCESS_PROVENANCE_ARTIFACT, checksum)
    except DuplicateArtifactError as exc:
        raise ProvenanceError(
            "write-once violation recording the pre-access provenance subset "
            f"{PRE_ACCESS_PROVENANCE_ARTIFACT!r}: {exc}"
        ) from exc
    return checksum


def persist_pre_access_ledger(*, run_dir: str | Path, ledger: RunLedger) -> Path:
    """Atomically persist and verify the pre-access ledger before seal opening."""
    ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)
    destination = Path(run_dir) / PRE_ACCESS_LEDGER_FILENAME
    text = json.dumps(ledger.to_dict(), sort_keys=True, separators=(",", ":"))
    try:
        atomic_write_once(destination, text)
    except FileExistsError as exc:
        raise ProvenanceError(
            f"pre-access ledger snapshot already exists at {str(destination)!r}; "
            "the seal lifecycle is write-once"
        ) from exc
    try:
        installed = RunLedger.read(destination)
    except Exception as exc:
        raise ProvenanceError(
            f"failed to read back pre-access ledger snapshot {str(destination)!r}: {exc}"
        ) from exc
    if installed != ledger:
        raise ProvenanceError("pre-access ledger snapshot failed post-install verification")
    return destination


def verify_upstream_before_access(
    *,
    expected_run_id: str,
    recomputed_run_id: str,
    upstream_ledger: RunLedger,
    required_artifacts: Sequence[str],
    expected_checksums: Mapping[str, str],
) -> None:
    """PRE-ACCESS gate: abort BEFORE seal access on any absence / mismatch.

    Runs entirely before the seal is touched. It raises :class:`ProvenanceError`
    — leaving the seal CLOSED — if any of the following hold:

    * the recomputed run id != the expected run id;
    * the required-artifact set is EMPTY (an empty set is itself an error; there
      is NO ``all([])`` vacuous-pass behaviour);
    * any required artifact is ABSENT from the upstream ledger;
    * any required artifact has no expected checksum supplied; or
    * any required artifact's ledger checksum != its expected checksum.

    All required artifacts are checked (no early success return); the first
    violation aborts. On a clean pass this returns ``None``.

    Parameters
    ----------
    expected_run_id : str
        The run id the run was registered under.
    recomputed_run_id : str
        The run id recomputed here (from :func:`recompute_run_id`).
    upstream_ledger : RunLedger
        The upstream provenance ledger whose artifacts are verified.
    required_artifacts : Sequence of str
        The artifact names that MUST be present and matching. Must be non-empty.
    expected_checksums : Mapping of str to str
        The expected SHA-256 for each required artifact.

    Raises
    ------
    ProvenanceError
        On a run-id mismatch, an empty required set, an absent artifact, a
        missing expected checksum, or a checksum mismatch — abort, seal closed.
    """
    if recomputed_run_id != expected_run_id:
        raise ProvenanceError(
            f"recomputed run id {recomputed_run_id!r} != expected {expected_run_id!r}; "
            "aborting before seal access (seal stays closed)."
        )

    required = tuple(required_artifacts)
    if not required:
        # No vacuous all([]) pass: an empty required set cannot certify anything.
        raise ProvenanceError(
            "required_artifacts is empty; the pre-access gate refuses to certify an "
            "empty upstream set (no all([]) pass). Aborting before seal access."
        )

    for name in required:
        if name not in expected_checksums:
            raise ProvenanceError(
                f"no expected checksum supplied for required artifact {name!r}; "
                "aborting before seal access (seal stays closed)."
            )
        try:
            recorded = upstream_ledger.artifact_sha(name)
        except LedgerError as exc:
            raise ProvenanceError(
                f"required upstream artifact {name!r} is ABSENT from the ledger: {exc}; "
                "aborting before seal access (seal stays closed)."
            ) from exc
        expected = expected_checksums[name]
        if recorded != expected:
            raise ProvenanceError(
                f"upstream artifact {name!r} checksum mismatch: ledger {recorded!r} != "
                f"expected {expected!r}; aborting before seal access (seal stays closed)."
            )


def check_post_access_consistency(
    *,
    recomputed_run_id: str,
    seal_audit_run_id: str,
    seal_audit_request_checksum: str,
    observed_request_checksum: str,
    provenance: Phase2bProvenance,
    persisted_pre_access_checksum: str,
    result_checksums: Mapping[str, str],
    expected_result_checksums: Mapping[str, str],
) -> PostAccessStatus:
    """POST-ACCESS path: return OK / INVALID — NEVER raise on an inconsistency.

    Evaluated AFTER the single sealed opening, when the seal is already consumed.
    A detected inconsistency must NOT raise into a crash (that would lose the
    fact that the seal was burned); instead it returns
    :class:`PostAccessStatus.INVALID` so the terminal writer (Task 7) records a
    terminal INVALID artifact. A fully-consistent post-access state returns
    :class:`PostAccessStatus.OK`.

    The state is INVALID if any of the following hold:

    * the seal-audit's recorded run id != the recomputed run id;
    * the observed request checksum != the seal-audit's request checksum;
    * the provenance record's pre-access subset checksum != the PERSISTED
      pre-access checksum (a real cross-check against the write-once ledger);
    * any regime result checksum != its expected value, or the result-checksum
      key sets differ.

    Parameters
    ----------
    recomputed_run_id : str
        The run id recomputed for this run.
    seal_audit_run_id : str
        The run id recorded in the consumed seal audit.
    seal_audit_request_checksum : str
        The request checksum recorded in the seal audit.
    observed_request_checksum : str
        The request checksum observed for the sealed access.
    provenance : Phase2bProvenance
        The COMPLETE provenance record for this run.
    persisted_pre_access_checksum : str
        The pre-access digest-subset checksum PERSISTED into the write-once
        ledger before access (:func:`record_pre_access_provenance`). The
        provenance leg cross-checks the recomputed subset checksum against this
        persisted value — a real tamper detector, not a self-reference.
    result_checksums : Mapping of str to str
        Observed regime result checksums (e.g. ``{"double", "single"}``).
    expected_result_checksums : Mapping of str to str
        The expected regime result checksums.

    Returns
    -------
    PostAccessStatus
        ``OK`` if every post-access check passes; ``INVALID`` otherwise. Never
        raises on a detected inconsistency.
    """
    if seal_audit_run_id != recomputed_run_id:
        return PostAccessStatus.INVALID

    if observed_request_checksum != seal_audit_request_checksum:
        return PostAccessStatus.INVALID

    if provenance.pre_access_checksum != persisted_pre_access_checksum:
        return PostAccessStatus.INVALID

    if set(result_checksums) != set(expected_result_checksums):
        return PostAccessStatus.INVALID
    for key, expected in expected_result_checksums.items():
        if result_checksums.get(key) != expected:
            return PostAccessStatus.INVALID

    return PostAccessStatus.OK
