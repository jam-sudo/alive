"""``phase2b`` subcommand orchestration (COMPOSE production driver, spec §3.3).

The LAST of the three driver subcommands (canonical order ``phase2a → preflight
→ phase2b``) and the **single sealed-store construction point in the entire
driver** (spec §4). Everything before the seal is a re-verification of the
non-sealed state the earlier subcommands installed; the store is built HERE and
ONLY here, so this module is the one place permitted to import/construct
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` /
:func:`~alive.compose.outcome_store.build_fixture_outcome_store` (Task 12 asserts
this structurally). It re-implements no science — it verifies, assembles the
sealed store, hands off to the library entry point, and re-reads the durable
export.

Steps (spec §3.3 steps 0-6):

0. acquire the non-blocking OS-exclusive driver lock ``run_dir/phase2b.lock`` and
   assert the phase2b ENTRY roster (the 4 phase2a artifacts + the confirmation
   manifest required; terminal / audit / pre-access / durable forbidden) — a
   stray seal-adjacent artifact or a missing confirmation fails closed here;
1. (scientific only) re-verify the clean-git + activation carrier state BEFORE
   confirmation — the fixture path has no real Git tree (``git_clean == True``);
2. reload the frozen bundle + RE-READ the persisted phase2a ledger and run the
   outcome-free :func:`~alive.compose.preflight.run_preflight` gate (re-verifying
   CONTINUE + every pre-seal checksum) to obtain the frozen
   :class:`~alive.compose.preflight.EvaluationLock`;
3. re-verify the installed ``seal_confirmation_manifest.json`` via
   :func:`~alive.compose.driver.confirmation.verify_seal_confirmation_manifest`
   — the ``--confirm-seal`` token must equal the manifest's FULL
   ``confirmation_checksum`` (a run-id-only token is rejected), THEN the manifest
   is reconstructed byte-for-byte from the CURRENT non-sealed inputs (assembled
   by the SHARED Task-8 :func:`~alive.compose.driver.preflight_cmd.build_confirmation_inputs`).
   The sealed access count is still 0;
4. ONLY after confirmation: integrity-check and retain the sealed source
   (``O_NOFOLLOW`` regular-file fd, ``(device, inode, size, mtime_ns)`` compared
   around a streamed hash, digest verified), check the mode-specific audit
   destination is absent, then **construct the lazy sealed store in THIS
   function only** with
   ``audit_path = <run_dir>/audit.jsonl`` for fixtures or the canonical
   protocol-global audit under ``approved_artifacts_root`` for scientific runs;
5. dispatch the correct library entry point (``run_phase2b_fixture`` /
   ``run_phase2b``); the seal is opened EXACTLY once inside it, after which the
   obs-alignment validator parses metadata and materialisation reads rows through
   an fd-backed path for the exact inode hashed in step 4;
6. INDEPENDENTLY re-read ``phase2b_durable_commit.json`` (canonical bytes +
   self-checksum + every recorded file SHA), then map the terminal state to an
   exit code. This runs AFTER the seal is consumed, so a present-but-corrupt
   marker is a POST-seal failure: it RETURNS the non-``COMPLETE`` exit (30) with
   a single stderr diagnostic — symmetric with the absent-marker case — rather
   than raising a (pre-seal-looking) ``Phase2bSubcommandError``.

Output discipline (spec §3.3). Nothing scientific is emitted before the step-6
durable re-read; this subcommand returns only a terminal-state exit code and
never an aggregate, verdict, or per-pair value.

Exit codes (§1.1): ``0`` = a ``COMPLETE`` terminal with a verified durable commit
marker; ``30`` = a non-``COMPLETE`` terminal (``INVALID`` / ``ABORTED``) OR an
incomplete/corrupt durable export (an absent marker, or a present marker that
fails its self-checksum / recorded file-SHA re-verification — a POST-seal
failure, RETURNED not raised, since the seal was already consumed). A pre-seal
violation (roster, confirmation, source integrity) fails closed by RAISING — the
seal is never opened, no audit is written, and no terminal artifact is left
behind. Obs-alignment is deliberately post-claim: a mismatch returns 30 after
durably recording ``ABORTED_AFTER_SEAL``.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §3.3.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping

import anndata

from alive.compose.approximation_bias import (
    ApproximationBiasEvidence,
    ApproximationBiasValidationError,
)
from alive.compose.config2 import load_compose_phase2_config
from alive.compose.driver.bias_report_preseal import (
    ApproximationBiasDeclarationError,
    gears_approximation_bias_sha,
    resolve_pinned_approximation_bias_evidence,
)
from alive.compose.driver.confirmation import verify_seal_confirmation_manifest
from alive.compose.driver.preflight_cmd import build_confirmation_inputs
from alive.compose.driver.run_dir_state import (
    DRIVER_LOCK_FILE,
    TERMINAL_BASENAMES,
    RunDirStateError,
    assert_run_dir_roster,
)
from alive.compose.driver.run_spec import (
    RUN_PRODUCED_BASENAMES,
    ResolvedRunSpec,
    load_resolved_run_spec,
)
from alive.compose.driver.seal_boundary import (
    fixture_seal_audit_path,
    scientific_protocol_seal_audit_path,
)
from alive.compose.durable import (
    COMMIT_CHECKSUM_FIELD,
    DURABLE_COMMIT_FILENAME,
    SEAL_AUDIT_FILENAME,
)
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.outcome_store import (
    ComposeOutcomeStore,
    build_fixture_outcome_store,
    validate_pair_index_against_source_obs,
)
from alive.compose.phase2b import run_phase2b, run_phase2b_fixture
from alive.compose.preflight import run_preflight
from alive.compose.roles import ROLE_NAMES
from alive.compose.terminal import TerminalState
from alive.provenance import RunLedger, sha256_file, sha256_json

__all__ = [
    "PHASE2B_COMPLETE_EXIT",
    "PHASE2B_NONCOMPLETE_EXIT",
    "Phase2bSubcommandError",
    "run_phase2b_subcommand",
]

#: Exit code for a ``COMPLETE`` terminal with a verified durable commit marker.
PHASE2B_COMPLETE_EXIT = 0

#: Exit code for a non-``COMPLETE`` terminal (``INVALID`` / ``ABORTED``) OR an
#: incomplete durable export (the commit marker absent).
PHASE2B_NONCOMPLETE_EXIT = 30

#: Streaming-hash chunk size for the sealed-source integrity check.
_HASH_CHUNK = 1 << 20

#: The durable commit-marker file-SHA entry keys that carry a ``{filename,
#: sha256}`` pair the step-6 re-read cross-checks against the on-disk bytes. A
#: summary-bearing marker (``COMPLETE`` / ``INVALID``) carries all five; an
#: ``ABORTED_AFTER_SEAL`` marker omits ``registered_summary``.
_MARKER_FILE_ENTRY_KEYS: tuple[str, ...] = (
    "terminal",
    "registered_summary",
    "final_ledger",
    "pre_access_ledger",
    "seed_variability",
)


class Phase2bSubcommandError(RuntimeError):
    """Raised on a driver-level phase2b orchestration failure (fail-closed).

    Distinct from the library entry point's own errors and from the seal-boundary
    :class:`~alive.compose.outcome_store.ComposeSealingError`. Covers a failed
    driver-lock acquisition (a concurrent phase2b/recover), a sealed-source
    integrity failure (symlink / non-regular node / identity change during
    hashing / digest mismatch), an already-existing mode-specific audit
    destination, and a durable commit marker that re-reads inconsistently.
    """


# --------------------------------------------------------------------------- #
# Public subcommand
# --------------------------------------------------------------------------- #


def run_phase2b_subcommand(
    run_spec: Any,
    *,
    approved_artifacts_root: str | Path,
    run_dir: str | Path,
    confirm_seal_token: str,
) -> int:
    """Construct the sealed store and run the one-time Phase-2b evaluation (§3.3).

    Parameters
    ----------
    run_spec
        The stage-1 DATA carrier (locally the committed fixture builder's
        :class:`~alive.compose.driver.fixture_builder.FixtureBundle`). It carries
        the canonical ResolvedRunSpec path (``spec_path``), the LIVE response
        artifact (``response_artifact``), and the sealed-outcome DATA
        (``sealed_outcome`` — the source path + expected digest, the ``pair_index``,
        the split + pair-index manifests, the corpus attestation triple, and the
        perturbation-column / combo-separator rules) a sealed store is built FROM.
        No sealed store is ever carried; it is constructed here.
    approved_artifacts_root
        The out-of-band CLI trust root; its canonical realpath must equal the
        ResolvedRunSpec's declared ``approved_artifacts_root``.
    run_dir
        The shared run directory. Must hold EXACTLY the 4 phase2a artifacts + the
        confirmation manifest at entry (§7.1); the driver lock is the only new
        install before the seal opens.
    confirm_seal_token
        The ``--confirm-seal`` token; must equal the installed manifest's FULL
        ``confirmation_checksum`` (never the recomputable run id).

    Returns
    -------
    int
        ``0`` for a ``COMPLETE`` terminal with a verified durable commit marker;
        ``30`` for a non-``COMPLETE`` terminal or an incomplete durable export.

    Raises
    ------
    RunDirStateError
        If the phase2b entry roster is violated (checked at step 0).
    RunSpecError
        If the ResolvedRunSpec fails validation.
    ConfirmationError
        If the ``--confirm-seal`` token or the manifest reconstruction fails.
    ComposeSealingError
        If the pair index does not align with the source obs labels, or the
        sealed store rejects its inputs — raised BEFORE any seal access.
    Phase2bSubcommandError
        On a lock/integrity/audit-destination/durable-marker failure.
    """
    run_dir = Path(run_dir)

    # Step 0: acquire the non-blocking OS-exclusive driver lock, then assert the
    # phase2b entry roster. Both fail closed BEFORE any store construction; the
    # roster forbids a stray audit / terminal / durable artifact and requires the
    # confirmation manifest, so omitting preflight fails here.
    with _driver_lock(run_dir):
        try:
            assert_run_dir_roster(run_dir, "phase2b")
        except RunDirStateError as exc:
            # The phase2b entry roster FORBIDS a terminal artifact, so the very
            # thing that trips it can be proof the seal was already consumed. Left
            # to propagate, that reached the CLI and returned exit 10 -- "the seal
            # was NOT consumed" -- with the terminal sitting on disk saying
            # otherwise (2026-08-02 review; the same defect the recover branch had).
            # Decide on filesystem EVIDENCE, exactly as ``_seal_consumed`` does for
            # the dispatch, not on the exception type. The scientific audit is
            # protocol-global rather than run-local, so the terminal is the reliable
            # local witness in both modes.
            if _prior_seal_evidence(run_dir):
                # Keep the registered ``stage: ExceptionName: message`` shape: the
                # runbook's operator table is keyed on the CLASS NAME, and the first
                # version of this line dropped it, leaving the operator without a
                # lookup key (2026-08-03 review).
                print(
                    f"phase2b: {type(exc).__name__}: {exc} "
                    "[run_dir carries a terminal or a burned seal audit: an earlier "
                    "run consumed the seal -- use `recover`, do not re-run phase2b]",
                    file=sys.stderr,
                )
                return PHASE2B_NONCOMPLETE_EXIT
            raise
        return _run_confirmed_phase2b(
            run_spec,
            approved_artifacts_root=approved_artifacts_root,
            run_dir=run_dir,
            confirm_seal_token=confirm_seal_token,
        )


def _run_confirmed_phase2b(
    run_spec: Any,
    *,
    approved_artifacts_root: str | Path,
    run_dir: Path,
    confirm_seal_token: str,
) -> int:
    """Steps 1-6, executed under the acquired driver lock."""
    # Step 1/2 setup: load + validate the immutable ResolvedRunSpec (trust
    # boundary), the config, the frozen bundle, and RE-READ the persisted phase2a
    # ledger (never reconstructed — that would make the ledger↔bundle check a
    # tautology).
    spec_path = Path(run_spec.spec_path)
    mode = _peek_mode(spec_path)
    spec = load_resolved_run_spec(
        spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected=mode
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    approximation_bias_report_evidence = _resolve_approximation_bias_report(
        spec, config, response_artifact=run_spec.response_artifact
    )
    bundle = FrozenPredictionBundle.load(run_dir / RUN_PRODUCED_BASENAMES["frozen_bundle"])
    ledger_path = run_dir / RUN_PRODUCED_BASENAMES["run_ledger"]
    ledger = RunLedger.read(ledger_path)

    sealed_outcome = run_spec.sealed_outcome
    response_artifact = run_spec.response_artifact
    payload_response = {
        "response_space": response_artifact["response_space"],
        "control_mean": response_artifact["control_mean"],
    }
    pair_manifest = sealed_outcome["manifest"]  # the split manifest (roles + checksum)

    # Step 1: scientific-only clean-git + activation re-verification (before
    # confirmation). Fixture mode has no real Git tree (git_clean == True).
    git_clean = _resolve_git_clean(spec, run_spec)

    # Step 2: the outcome-free preflight gate re-verifies CONTINUE + every
    # pre-seal checksum and yields the frozen EvaluationLock (the seal is
    # untouched; a rejection raises PreflightError, leaving no terminal/audit).
    lock = run_preflight(
        bundle=bundle,
        pair_manifest=pair_manifest,
        config=config,
        data_card_digest=spec.data_card_digest,
        raw_or_source_digest=spec.raw_or_source_digest,
        sequence_mapping_digest=spec.sequence_mapping_digest,
        ledger=ledger,
        expected_response_dim=int(response_artifact["response_space"].pca_dim),
    )

    # Step 3: re-verify the installed confirmation manifest against the token FIRST
    # (a run-id-only token is rejected), then require the manifest to reconstruct
    # byte-for-byte from the CURRENT non-sealed inputs (assembled by the SHARED
    # Task-8 helper — never a divergent copy). The sealed access count is still 0.
    reconstruct_inputs = build_confirmation_inputs(
        spec=spec,
        config=config,
        ledger=ledger,
        ledger_path=ledger_path,
        lock=lock,
        bundle=bundle,
        git_clean=git_clean,
    )
    verify_seal_confirmation_manifest(
        run_dir / RUN_PRODUCED_BASENAMES["seal_confirmation_manifest"],
        confirm_seal_token,
        reconstruct_inputs=reconstruct_inputs,
    )

    # Step 4: ONLY after confirmation. Open + integrity-check the sealed source once,
    # keep that exact descriptor alive, check the mode-specific audit destination and
    # construct a LAZY sealed store. Source obs/X are parsed only after its durable
    # audit claim (§4).
    audit_path, audit_parent = _resolve_seal_audit_destination(spec, run_dir=run_dir)
    store_context = _build_sealed_store(
        spec=spec,
        audit_path=audit_path,
        audit_parent=audit_parent,
        sealed_outcome=sealed_outcome,
        pair_manifest=pair_manifest,
    )

    # Step 5: dispatch the correct library entry point. The seal opens EXACTLY
    # once inside it; every consumed access burns the mode-specific audit + writes a
    # terminal artifact. A RAISE from the library AFTER that consumption (the
    # abort path re-raises the boundary exception; a normal-path durable-finalize
    # failure raises DurableLedgerError) is a POST-seal failure: it is made
    # SYMMETRIC with step 6 — emit ONE diagnostic and RETURN 30 (recover can
    # salvage the consumed-seal terminal), NEVER let it propagate to the CLI,
    # which would mislabel a consumed seal as the pre-seal exit 10 (or crash to
    # exit 1 for the unlisted DurableLedgerError). A genuinely PRE-seal raise
    # (nothing consumed → audit still empty/absent) is re-raised so the CLI's
    # pre-seal mapping stays correct.
    with store_context as outcome_store:
        try:
            if spec.mode == "fixture":
                result = run_phase2b_fixture(
                    run_dir=run_dir,
                    outcome_store=outcome_store,
                    frozen_bundle=bundle,
                    pair_manifest=pair_manifest,
                    response_artifact=payload_response,
                    config=config,
                    ledger=ledger,
                )
            else:
                # Scientific dispatch (a PREPARE obligation; NOT exercised by the local
                # fixture path). run_phase2b re-verifies activation + clean git itself.
                seed_report_path = (
                    run_dir / RUN_PRODUCED_BASENAMES["phase2a_seed_variability_report"]
                )
                scientific_response = {
                    **payload_response,
                    "checksum": response_artifact["combined_checksum"],
                }
                result = run_phase2b(
                    run_dir=run_dir,
                    outcome_store=outcome_store,
                    frozen_bundle=bundle,
                    pair_manifest=pair_manifest,
                    response_artifact=scientific_response,
                    config=config,
                    ledger=ledger,
                    activation_record=run_spec.activation_record,
                    git_is_clean=git_clean,
                    provenance_inputs=getattr(run_spec, "provenance_inputs", None),
                    oof_manifest_path=run_dir / RUN_PRODUCED_BASENAMES["oof_manifest"],
                    oof_manifest_checksum=bundle.dev_diagnostics["oof_fold_manifest_checksum"],
                    seed_variability_report_path=seed_report_path,
                    seed_variability_report_checksum=sha256_file(seed_report_path),
                    approximation_bias_report_evidence=approximation_bias_report_evidence,
                )
        except Exception as exc:  # noqa: BLE001 - re-raised unless the seal was consumed
            if _seal_consumed(audit_path):
                print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
                return PHASE2B_NONCOMPLETE_EXIT
            raise

    # Step 6: INDEPENDENTLY re-read the durable commit marker (never the returned
    # result alone), then map the terminal state to an exit code. Nothing
    # scientific is emitted here — only the terminal-state exit code.
    #
    # This runs AFTER the seal is consumed (step 5 opened it EXACTLY once, writing
    # a terminal + audit). A PRESENT-but-CORRUPT marker (a self-checksum or
    # recorded file-SHA mismatch) is therefore a genuinely-POST-seal failure: it
    # is made SYMMETRIC with the ABSENT-marker case (which returns the
    # non-COMPLETE exit via ``marker_verified is False``) — emit ONE diagnostic
    # and RETURN 30, never raise. Letting the Phase2bSubcommandError propagate
    # here would surface a consumed-seal failure to the CLI, which maps
    # Phase2bSubcommandError to the PRE-seal exit 10 ("no seal consumed"),
    # mislabelling a post-seal failure. No seal/terminal/audit state is touched.
    try:
        marker_verified = _reread_durable_commit(
            run_dir, expected_checksum=result.durable_commit_checksum
        )
    except Phase2bSubcommandError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return PHASE2B_NONCOMPLETE_EXIT
    except (OSError, KeyError, ValueError, TypeError) as exc:
        # The reasoning above is about the SEAL STATE, not the exception type, so it
        # cannot stop at one class (2026-08-02 review). ``_reread_durable_commit``
        # reads the marker and every file it records, so a marker that is present but
        # malformed in a way the validator does not model first surfaces as a builtin:
        # ``KeyError`` on a missing ``filename``/``sha256`` entry, ``OSError`` when a
        # marker-recorded file is unreadable or gone, a decode/coercion ``ValueError``.
        # Every one of those happens AFTER the seal was consumed, so exit 1 (the
        # registered bug escape) is the wrong signal: the operator's next action is
        # ``recover``, which is what 30 tells them. Narrow by construction -- this
        # wraps a single re-read of already-written bytes, not a library call.
        print(
            f"durable marker re-read failed post-seal: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return PHASE2B_NONCOMPLETE_EXIT
    if result.terminal_state == TerminalState.COMPLETE and marker_verified:
        return PHASE2B_COMPLETE_EXIT
    return PHASE2B_NONCOMPLETE_EXIT


# --------------------------------------------------------------------------- #
# Step 0: driver lock
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _driver_lock(run_dir: Path) -> Iterator[None]:
    """Hold the non-blocking OS-exclusive ``run_dir/phase2b.lock`` (spec §3.3 step 0).

    Uses ``flock(LOCK_EX | LOCK_NB)`` on a dedicated lock file so a concurrent
    ``phase2b`` / ``recover`` fails closed immediately (never blocks) and the lock
    is released even if this process dies. The lock file itself is an ephemeral
    artifact the phase2b/recover rosters allow.

    Raises
    ------
    Phase2bSubcommandError
        If the lock is already held (a concurrent driver run) or cannot be opened.
    """
    lock_path = run_dir / DRIVER_LOCK_FILE
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise Phase2bSubcommandError(
            f"cannot open the phase2b driver lock {str(lock_path)!r}: {exc}"
        ) from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Phase2bSubcommandError(
                f"another phase2b/recover holds the driver lock {str(lock_path)!r}; "
                "refusing to run concurrently"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# Step 4: sealed-source integrity + sealed-store construction (the SOLE point)
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _build_sealed_store(
    *,
    spec: ResolvedRunSpec,
    audit_path: Path,
    audit_parent: Path,
    sealed_outcome: Mapping[str, Any],
    pair_manifest: Mapping[str, Any],
) -> Iterator[ComposeOutcomeStore]:
    """Construct the sealed outcome store — the driver's SOLE construction site (§4).

    Runs entirely AFTER confirmation: integrity-check and retain an open
    descriptor for the sealed source file, enforce the mode-specific audit
    destination is absent, and enforce each pair's declared role against the
    split role names.  It then yields a lazy store whose source-observation
    validation runs only after :meth:`ComposeOutcomeStore.claim_sealed_access`
    has durably consumed the seal.  The retained descriptor ensures validation
    and materialisation reopen the exact inode whose bytes were hashed, even if
    the source pathname is replaced concurrently. Fixture mode mints a sanctioned
    :class:`~alive.compose.outcome_store.FixtureOutcomeStore` via the allowlisted
    :func:`~alive.compose.outcome_store.build_fixture_outcome_store`; scientific
    mode builds a plain :class:`~alive.compose.outcome_store.ComposeOutcomeStore`.
    """
    pair_index = sealed_outcome["pair_index"]
    source_path = Path(sealed_outcome["source_path"])
    expected_source_sha = sealed_outcome["source_file_sha256"]
    perturbation_col = sealed_outcome["perturbation_column"]
    combo_sep = sealed_outcome["combo_sep"]

    # Cross-check the two carrier artifacts agree on the expected source digest
    # (the pair-index manifest and the declared sealed-input digest), then verify
    # the source file bytes against it (O_NOFOLLOW, identity-stable around hashing).
    manifest_source_sha = sealed_outcome["pair_index_manifest"]["source_file_sha256"]
    if manifest_source_sha != expected_source_sha:
        raise Phase2bSubcommandError(
            "sealed-outcome carrier disagrees on the expected source digest: "
            f"pair_index_manifest ({manifest_source_sha!r}) != declared "
            f"({expected_source_sha!r})"
        )
    # ⚑ The recover-critical audit destination is resolved before construction:
    # run-local for fixtures, protocol-global for scientific mode. Any existing
    # node means the write-once claim is unavailable or the seal was consumed.
    _assert_audit_destination_free(audit_path, expected_parent=audit_parent)

    # Enforce each pair's declared role against the registered split roles (a
    # bogus role fails closed before the seal is built).
    _assert_pair_roles(sealed_outcome["pair_index_manifest"])

    with _open_verified_sealed_source(source_path, expected_source_sha) as verified_source:
        opened_source: Any | None = None

        def _validate_source_obs_after_claim() -> Any:
            """Open once post-claim, validate, then retain this exact backed source."""
            nonlocal opened_source
            source_obj = anndata.read_h5ad(verified_source, backed="r")
            try:
                validate_pair_index_against_source_obs(
                    source_obj,
                    pair_index,
                    pair_manifest,
                    perturbation_col=perturbation_col,
                    combo_sep=combo_sep,
                )
            except BaseException:
                source_obj.file.close()
                raise
            opened_source = source_obj
            return source_obj

        if spec.mode == "fixture":
            # Fixture-vs-real-source byte comparison stays OFF (validated by index +
            # attestation, not raw source bytes): the allowlisted attestation triple
            # is passed through and checked against the committed allowlist only.
            outcome_store = build_fixture_outcome_store(
                pair_index,
                verified_source,
                pair_manifest,
                audit_path=audit_path,
                corpus_id=sealed_outcome["corpus_id"],
                source_sha256=sealed_outcome["source_sha256"],
                builder_code_sha256=sealed_outcome["builder_code_sha256"],
                materialization_validator=_validate_source_obs_after_claim,
            )
        else:
            outcome_store = ComposeOutcomeStore(
                pair_index,
                verified_source,
                pair_manifest,
                audit_path=audit_path,
                materialization_validator=_validate_source_obs_after_claim,
            )
        try:
            yield outcome_store
        finally:
            if opened_source is not None:
                opened_source.file.close()


@contextlib.contextmanager
def _open_verified_sealed_source(source_path: Path, expected_sha: str) -> Iterator[Path]:
    """Yield an fd-backed path to the integrity-checked sealed source.

    Opens the source with ``O_NOFOLLOW`` (rejecting a symlink final component),
    fstat-verifies it is a regular file, captures its
    ``(device, inode, size, mtime_ns)`` identity, streams the SHA-256, then
    re-captures the identity and requires it unchanged (a mutation during
    hashing fails closed). The streamed digest must equal ``expected_sha``.
    The original descriptor remains open while the yielded ``/proc/self/fd`` or
    ``/dev/fd`` path is used, closing the hash-then-reopen pathname race.

    Raises
    ------
    Phase2bSubcommandError
        On a symlink / non-regular node, an identity change during hashing, an
        unreadable file, a digest mismatch, or an unavailable/mismatched
        descriptor-backed path.
    """
    if source_path.is_symlink():
        raise Phase2bSubcommandError(
            f"sealed source {str(source_path)!r} is a symlink (node-kind policy)"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(source_path, flags)
    except OSError as exc:
        raise Phase2bSubcommandError(
            f"cannot open sealed source {str(source_path)!r} (O_NOFOLLOW): {exc}"
        ) from exc
    try:
        pre = os.fstat(fd)
        if not stat.S_ISREG(pre.st_mode):
            raise Phase2bSubcommandError(
                f"sealed source {str(source_path)!r} is not a regular file (node-kind policy)"
            )
        identity_before = (pre.st_dev, pre.st_ino, pre.st_size, pre.st_mtime_ns)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, _HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
        post = os.fstat(fd)
        identity_after = (post.st_dev, post.st_ino, post.st_size, post.st_mtime_ns)
        if identity_before != identity_after:
            raise Phase2bSubcommandError(
                f"sealed source {str(source_path)!r} changed identity during hashing "
                f"(before={identity_before!r} after={identity_after!r})"
            )
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            raise Phase2bSubcommandError(
                f"sealed source {str(source_path)!r} digest mismatch "
                f"(expected {expected_sha!r}, got {actual_sha!r})"
            )

        os.lseek(fd, 0, os.SEEK_SET)
        descriptor_path: Path | None = None
        for candidate in (Path(f"/proc/self/fd/{fd}"), Path(f"/dev/fd/{fd}")):
            try:
                candidate_fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            except OSError:
                continue
            try:
                candidate_stat = os.fstat(candidate_fd)
                candidate_identity = (
                    candidate_stat.st_dev,
                    candidate_stat.st_ino,
                    candidate_stat.st_size,
                    candidate_stat.st_mtime_ns,
                )
            finally:
                os.close(candidate_fd)
            if candidate_identity == identity_after:
                descriptor_path = candidate
                break
        if descriptor_path is None:
            raise Phase2bSubcommandError(
                "cannot obtain an identity-matched descriptor path for sealed source "
                f"{str(source_path)!r}; refusing a pathname reopen"
            )
        yield descriptor_path

        # --- post-hash window: prove the bytes did not change under us ---------
        # 2026-08-30, `seal.verified-fd-posthash-mutation`, reproduced independently
        # on both sides of the audit loop: descriptor pinning defeats a *pathname*
        # swap, but not an IN-PLACE write to the inode we hold open. Measured on the
        # real function: `same_inode=True`, verified digest != the digest of the
        # bytes actually read through the descriptor.
        #
        # Prevention is not available at this layer -- a local writer with write
        # permission can modify a file we hold read-only, and nothing here can stop
        # it. What IS available is making the divergence impossible to go unnoticed,
        # which is the property the seal's evidence actually rests on: "the bytes we
        # recorded as verified are the bytes we consumed" must be true or the run
        # must fail. So the digest is re-streamed through the SAME descriptor after
        # consumption and must still equal the declared one.
        #
        # This runs only on the normal path, never in `finally`: on an exception the
        # original failure is the one that matters and must not be masked.
        #
        # Cost measured on the real sealed source (0.70 GB): 0.2 s. Once per run.
        os.lseek(fd, 0, os.SEEK_SET)
        post = hashlib.sha256()
        while True:
            chunk = os.read(fd, _HASH_CHUNK)
            if not chunk:
                break
            post.update(chunk)
        post_stat = os.fstat(fd)
        identity_final = (
            post_stat.st_dev,
            post_stat.st_ino,
            post_stat.st_size,
            post_stat.st_mtime_ns,
        )
        post_sha = post.hexdigest()
        if post_sha != expected_sha:
            raise Phase2bSubcommandError(
                f"sealed source {str(source_path)!r} was modified IN PLACE while it was open: "
                f"the bytes verified before consumption hash to {expected_sha!r} but the same "
                f"descriptor now hashes to {post_sha!r}. The inode is unchanged "
                f"(identity before={identity_after!r} after={identity_final!r}), so a pathname "
                "check could not have seen this. Fail closed: what was consumed is not what was "
                "verified."
            )
        if identity_final != identity_after:
            raise Phase2bSubcommandError(
                f"sealed source {str(source_path)!r} changed identity while it was open "
                f"(before={identity_after!r} after={identity_final!r}) even though its bytes still "
                "hash to the declared digest. Fail closed rather than reason about how."
            )
    finally:
        os.close(fd)


def _resolve_approximation_bias_report(
    spec: ResolvedRunSpec, config: Any, *, response_artifact: Mapping[str, Any]
) -> ApproximationBiasEvidence | None:
    """Capture and validate config-pinned report bytes before building a store."""
    if spec.mode != "scientific":
        if gears_approximation_bias_sha(config) is not None:
            raise Phase2bSubcommandError(
                "fixture phase2b does not accept a config-pinned approximation-bias report"
            )
        return None
    if spec.scientific is None:  # pragma: no cover - schema already proves this
        raise Phase2bSubcommandError("scientific run spec has no scientific block")
    try:
        return resolve_pinned_approximation_bias_evidence(
            spec, config, response_artifact=response_artifact
        )
    except ApproximationBiasDeclarationError as exc:
        raise Phase2bSubcommandError(str(exc)) from exc
    except (OSError, ApproximationBiasValidationError) as exc:
        raise Phase2bSubcommandError(
            f"scientific approximation-bias report failed pre-seal validation: {exc}"
        ) from exc


def _resolve_seal_audit_destination(
    spec: ResolvedRunSpec,
    *,
    run_dir: Path,
) -> tuple[Path, Path]:
    """Resolve the only permitted audit path and its canonical parent.

    Fixtures retain the bounded run-local path. Scientific mode ignores the
    caller-selected run directory and converges every run of the registered
    protocol on one root-level, protocol-hash-derived write-once path. The
    declaration is checked again here at the last pre-construction boundary.
    """
    if spec.mode == "fixture":
        return fixture_seal_audit_path(run_dir), run_dir
    if spec.scientific is None:  # pragma: no cover - loader schema already proves this
        raise Phase2bSubcommandError("scientific run spec has no scientific block")
    expected = scientific_protocol_seal_audit_path(spec.approved_artifacts_root, spec.protocol)
    declared = Path(str(spec.scientific["sealed_input"]["audit_path"]))
    if declared != expected:
        raise Phase2bSubcommandError(
            f"scientific audit declaration {str(declared)!r} != canonical "
            f"protocol-global destination {str(expected)!r}"
        )
    return expected, Path(spec.approved_artifacts_root)


def _assert_audit_destination_free(audit_path: Path, *, expected_parent: Path) -> None:
    """Fail closed unless the canonical write-once audit destination is absent (§3.3).

    The audit file is the durable seal-consumption boundary; a pre-existing
    node means the atomic write-once claim cannot be installed (and a
    non-empty file means the seal was opened). It must be a direct child of the
    mode-specific canonical parent and must not be a symlink.

    Raises
    ------
    Phase2bSubcommandError
        If the audit destination is outside its canonical parent or any node
        already exists there.
    """
    if audit_path.parent.resolve() != expected_parent.resolve():
        raise Phase2bSubcommandError(
            f"audit destination {str(audit_path)!r} is not a direct child of its "
            f"canonical parent {str(expected_parent)!r}"
        )
    if audit_path.is_symlink():
        raise Phase2bSubcommandError(f"audit destination {str(audit_path)!r} is a symlink; refused")
    if audit_path.exists():
        raise Phase2bSubcommandError(
            f"audit destination {str(audit_path)!r} already exists; the atomic "
            "write-once seal claim is unavailable (refusing to construct a store)"
        )


def _prior_seal_evidence(run_dir: Path) -> bool:
    """Does ``run_dir`` carry local evidence that a previous run consumed the seal?

    Two witnesses, both written only after the seal is claimed:

    * a phase2b terminal (``TERMINAL_BASENAMES``);
    * the run-local seal audit (``SEAL_AUDIT_FILENAME``), which is the fixture-mode
      consumption boundary and is exactly the state
      :func:`~alive.compose.driver.run_dir_state.assert_run_dir_roster` ACCEPTS for
      ``recover`` -- audit burned, terminal not yet written.

    An earlier version of this check looked at terminals only (2026-08-02) and so
    still reported that audit-only crash state as a pre-seal rejection, while the
    recover roster in the same module accepted the same directory as post-seal. Two
    rosters disagreeing about one directory is the defect; the audit was the witness
    already imported next door (2026-08-03 review).

    Reads NAMES only -- no contents, no store, no audit records.
    """
    try:
        present = {entry.name for entry in run_dir.iterdir()}
    except OSError:
        # Unreadable run_dir: consumption unknown. Same asymmetry as
        # ``_seal_consumed`` -- never claim "not consumed" on missing information.
        return True
    return bool(present & (TERMINAL_BASENAMES | {SEAL_AUDIT_FILENAME}))


def _seal_consumed(audit_path: Path) -> bool:
    """Return ``True`` once the seal's durable audit carries content (§3.3 step 5).

    The seal — opened EXACTLY once inside ``run_phase2b[_fixture]`` — burns the
    mode-specific audit path as its durable consumption boundary, the counterpart to
    the absence :func:`_assert_audit_destination_free` requires BEFORE store
    construction. NOT its exact inverse any more: that function still uses
    ``Path.exists()``/``Path.is_symlink()``, so the two apply different evidence
    rules to the same path (harmless today -- ``os.link`` fails ``EEXIST`` -- but
    recorded rather than left implied). A post-dispatch exception with a non-empty audit is
    therefore a POST-seal failure (the caller returns exit ``30`` + ``recover``
    salvages the terminal); an empty/absent audit means nothing was consumed (the
    caller re-raises so the CLI's pre-seal mapping stays correct).

    Parameters
    ----------
    audit_path : Path
        The already-validated audit path that is the seal-consumption boundary.

    Returns
    -------
    bool
        ``True`` if the audit exists and is non-empty, and ``True`` on ANY I/O
        error other than a plain absence -- see below.
    """
    # Fails CLOSED, deliberately. The previous form was
    # ``audit_path.exists() and audit_path.stat().st_size > 0``, which had two
    # defects.
    #
    # (1) ``Path.exists()`` ignores exactly ``ENOENT``/``ENOTDIR``/``EBADF``/
    # ``ELOOP`` and returns ``False`` for them, so a path that resolved through a
    # non-directory, a symlink loop, or a bad descriptor read as "nothing was
    # consumed" -- and a post-seal exception was then re-raised and reported by the
    # CLI as exit 10, "the seal was NOT consumed", about a seal that may well have
    # been burned. CORRECTION (2026-08-03 review): the first draft of this comment,
    # its commit message and the readiness entry all claimed ``exists()`` swallows
    # ``OSError`` GENERALLY and named EACCES/ESTALE/EIO/EMFILE. That is false on the
    # pinned interpreter -- those four RAISE, and so escaped as the uncontracted
    # exit 1 rather than as a false 10. Both are defects, but only the four errnos
    # above produced the false "not consumed". For the raising errnos this change is
    # exit 1 -> the contracted 30, which is also right (the seal state is unknown,
    # and the original post-seal exception is no longer replaced).
    #
    # (2) Between ``exists()`` and ``stat()`` the file could vanish, raising
    # ``FileNotFoundError`` from INSIDE the caller's ``except`` block and replacing
    # the original exception. One ``stat()`` closes both.
    #
    # Only a plain absence may be read as "not consumed". Anything else leaves
    # consumption UNKNOWN, and the two directions are not symmetric: guessing
    # "consumed" costs a ``recover``, guessing "not consumed" puts a false claim
    # about the seal into the operator's hands. The write itself is durable
    # (``io.atomic_write_once``: fsync -> link -> dir fsync), so there is no
    # zero-length window to worry about -- the audit is absent or complete.
    try:
        return audit_path.stat().st_size > 0
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _assert_pair_roles(pair_index_manifest: Mapping[str, Any]) -> None:
    """Fail closed unless every pair's declared role is a registered split role.

    Enforces each ``pairs[i].role`` against the canonical
    :data:`~alive.compose.roles.ROLE_NAMES` (a bogus role must never reach the
    seal boundary).

    Raises
    ------
    Phase2bSubcommandError
        On a pair entry whose ``role`` is not in ``ROLE_NAMES``.
    """
    for entry in pair_index_manifest["pairs"]:
        role = entry.get("role")
        if role not in ROLE_NAMES:
            raise Phase2bSubcommandError(
                f"pair {entry.get('gene_a')!r}/{entry.get('gene_b')!r} declares role "
                f"{role!r}, not one of the registered split roles {sorted(ROLE_NAMES)}"
            )


# --------------------------------------------------------------------------- #
# Step 6: independent durable commit-marker re-read
# --------------------------------------------------------------------------- #


def _reread_durable_commit(run_dir: Path, *, expected_checksum: str | None) -> bool:
    """Independently re-read + verify ``phase2b_durable_commit.json`` (spec §3.3 step 6).

    Re-reads the marker from disk (never trusting the returned result alone),
    requires canonical JSON, re-verifies the self-excluding ``commit_checksum``,
    cross-checks it against the result's ``durable_commit_checksum`` when present,
    and re-verifies every recorded file SHA against the on-disk bytes.

    Returns
    -------
    bool
        ``True`` if the marker is present and fully verified; ``False`` if the
        marker is ABSENT (an incomplete durable export → the caller maps to 30).

    Raises
    ------
    Phase2bSubcommandError
        If the marker is PRESENT but fails any integrity check (non-canonical
        bytes, a self-checksum mismatch, a checksum divergence from the result,
        or a file-SHA mismatch) — a corrupt export fails closed.

    Notes
    -----
    This helper runs at step 6, AFTER the seal is consumed, so its
    ``Phase2bSubcommandError`` is a POST-seal failure. The caller
    (:func:`_run_confirmed_phase2b`) therefore CATCHES it, emits one stderr
    diagnostic, and RETURNS the non-``COMPLETE`` exit (30) — symmetric with the
    ``False`` (absent-marker) return — rather than letting it propagate to the
    CLI, which would mislabel a consumed-seal failure as the pre-seal exit 10.
    """
    marker_path = run_dir / DURABLE_COMMIT_FILENAME
    if not marker_path.is_file():
        return False  # incomplete durable export (no marker installed)

    raw = marker_path.read_bytes()
    try:
        marker = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Phase2bSubcommandError(
            f"durable commit marker {str(marker_path)!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Phase2bSubcommandError(
            f"durable commit marker {str(marker_path)!r} is not a JSON object"
        )
    if raw != _canonical_bytes(marker):
        raise Phase2bSubcommandError(
            f"durable commit marker {str(marker_path)!r} is not canonical JSON"
        )
    declared = marker.get(COMMIT_CHECKSUM_FIELD)
    core = {k: v for k, v in marker.items() if k != COMMIT_CHECKSUM_FIELD}
    if sha256_json(core) != declared:
        raise Phase2bSubcommandError(
            f"durable commit marker {str(marker_path)!r} self-checksum failed re-verification"
        )
    if expected_checksum is not None and declared != expected_checksum:
        raise Phase2bSubcommandError(
            "durable commit marker checksum diverges from the returned result "
            f"(marker {declared!r} != result {expected_checksum!r})"
        )
    for key in _MARKER_FILE_ENTRY_KEYS:
        entry = marker.get(key)
        if entry is None:
            continue  # registered_summary is absent on the ABORTED reduced publish
        filename = entry["filename"]
        on_disk = hashlib.sha256((run_dir / filename).read_bytes()).hexdigest()
        if on_disk != entry["sha256"]:
            raise Phase2bSubcommandError(
                f"durable commit marker file-SHA for {filename!r} failed re-verification "
                f"(marker {entry['sha256']!r} != on-disk {on_disk!r})"
            )
    return True


# --------------------------------------------------------------------------- #
# Assembly helpers
# --------------------------------------------------------------------------- #


def _peek_mode(spec_path: Path) -> str:
    """Read the declared ``mode`` before the full load (loader re-validates it)."""
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Phase2bSubcommandError(f"cannot read ResolvedRunSpec {spec_path}: {exc}") from exc
    mode = raw.get("mode") if isinstance(raw, dict) else None
    if mode not in {"fixture", "scientific"}:
        raise Phase2bSubcommandError(f"ResolvedRunSpec declares an unrecognised mode {mode!r}")
    return mode


def _resolve_git_clean(spec: ResolvedRunSpec, run_spec: Any) -> bool:
    """Resolve the clean-git flag for the confirmation reconstruction + dispatch.

    Fixture mode has no real Git working tree (``approved_git_sha`` is a fixed
    placeholder), so the deterministic fixture value is ``True``. Scientific mode
    takes the carrier's verified ``git_is_clean`` and fails closed if it is absent
    or not a clean committed tree — a scientific sealed run must never proceed on
    an unverified / dirty tree (spec §3.3 step 1).
    """
    if spec.mode == "fixture":
        return True
    git_is_clean = getattr(run_spec, "git_is_clean", None)
    if git_is_clean is not True:
        raise Phase2bSubcommandError(
            "scientific phase2b requires a clean committed Git tree (git_is_clean is True) "
            f"from the run_spec carrier, got {git_is_clean!r}"
        )
    return True


def _canonical_bytes(obj: object) -> bytes:
    """Canonical JSON bytes (``sort_keys`` + compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
