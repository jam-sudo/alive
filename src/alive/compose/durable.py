"""D1 durable-publish finalizer for COMPOSE Phase-2b terminal outputs.

The single sealed terminal artifact is the authoritative recovery source (spec
§1). Individual files are installed atomically and write-once, but *set*
completeness is decided by ONE marker installed LAST —
``phase2b_durable_commit.json``. Absent that marker the durable export is
INCOMPLETE and only a recovery-only path may complete it; the seal is never
reopened (spec §1, §3.1).

:func:`finalize_phase2b_durable_outputs` reads the already-written durable inputs
— the sealed terminal, the persisted pre-access ledger snapshot, and the D2
seed-variability report — and publishes the DERIVED files. For a summary-bearing
(``COMPLETE`` / ``INVALID``) terminal there are three: the outcome-free
``phase2b_registered_summary.json`` (a byte-faithful copy+normalise of the
terminal's ``registered_summary``), ``phase2b_final_ledger.json`` (the pre-access
ledger snapshot + the terminal's embedded provenance expanded into individual
canonical entries + write-once file-SHA entries), and finally the single
``phase2b_durable_commit.json`` marker binding every file SHA with a self-excluding
``commit_checksum``. For an ``ABORTED_AFTER_SEAL`` terminal — which carries no
registered summary and no embedded provenance — it takes the REDUCED abort publish
(spec §3.3): no registered summary file, a final ledger over the pre-access snapshot
binding only the {terminal, seed} file SHAs (provenance comes from that snapshot,
not the absent terminal-embedded provenance), and a marker whose DETERMINISTIC field
set omits every summary field.

This module opens NO seal and constructs NO outcome store. It only reads durable
files and publishes derived files (forward publish + verification + idempotent
recovery). Every install routes through :func:`install_or_verify_exact`: an absent
destination is written atomically write-once, a byte/SHA-identical destination is a
no-op, and a DIFFERENT pre-existing destination fails closed (never overwritten).
This makes the forward publish idempotent and lets
:func:`recover_phase2b_durable_outputs` re-drive a crash-interrupted publish:
0 or ≥2 terminals fail closed, a lone terminal with no marker re-runs the matching
forward publish (§3.1 summary-bearing or §3.3 reduced abort; byte-identical
re-derivation ⇒ the SAME marker; NO seal is reopened), and a present marker is
VERIFIED ONLY (never rewritten). Recovery also verifies the seed-variability
artifact's actual regular-file bytes/SHA against the pre-access ledger record
(spec §3.2).

The whole-body ``terminal_payload_checksum`` is verified through the ONE shared
:func:`~alive.compose.terminal.canonicalize_terminal_checksum_input`, never by
``sha256_json`` over the raw decoded body — a real terminal carries finite floats
whose persisted JSON number differs from the ``float.hex()`` string the writer
hashed (spec §2, CLAUDE.md#provenance).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from alive.compose.config2 import (
    _EXPECTED_COMPARATOR_FAMILY,
    _EXPECTED_METHOD_ROSTER,
)

# LEAF module (it imports only `verdict2`), so importing it here creates no cycle: `phase2b`
# imports THIS module, which is exactly why the renderer could not stay in `phase2b`.
from alive.compose.headline import render_preregistered_headline
from alive.compose.provenance2 import (
    _DIGEST_ARTIFACTS,
    _EVIDENCE_ARTIFACTS,
    _POST_ACCESS_FIELDS,
    PRE_ACCESS_LEDGER_FILENAME,
    PRE_ACCESS_PROVENANCE_ARTIFACT,
)
from alive.compose.seed_variability import DEVELOPMENT_SEED_VARIABILITY_FILENAME
from alive.compose.terminal import (
    _COMMON_TERMINAL_FIELDS,
    _STATE_TERMINAL_FIELDS,
    TERMINAL_PAYLOAD_CHECKSUM_FIELD,
    Phase2bTerminal,
    TerminalError,
    TerminalState,
    _assert_no_raw_outcomes,
    canonicalize_terminal_checksum_input,
)
from alive.io import atomic_write_once
from alive.provenance import (
    DuplicateArtifactError,
    LedgerError,
    RunLedger,
    sha256_file,
    sha256_json,
)

#: The durable sealed-access audit filename (a direct child of the run dir), written
#: by :class:`~alive.compose.outcome_store.ComposeOutcomeStore` at ``claim_sealed_access``
#: (see :mod:`alive.cli`). Recovery reads it to synthesize the missing
#: ``ABORTED_AFTER_SEAL`` terminal for the ``audit=1`` / ``terminal=0`` crash state.
SEAL_AUDIT_FILENAME = "audit.jsonl"

#: Published derived-file names (all direct children of the run dir).
REGISTERED_SUMMARY_FILENAME = "phase2b_registered_summary.json"
FINAL_LEDGER_FILENAME = "phase2b_final_ledger.json"
DURABLE_COMMIT_FILENAME = "phase2b_durable_commit.json"

#: Versioned schema string carried by the durable commit marker.
DURABLE_COMMIT_SCHEMA = "compose_phase2b_durable_commit_v1"

#: The registered-summary schema the finalizer validates for a summary-bearing
#: terminal (the Task-5 v1 shape written by
#: :func:`alive.compose.phase2b.build_registered_evaluation_summary`). A summary
#: carrying any other schema fails closed.
_REGISTERED_SUMMARY_SCHEMA_V1 = "compose_registered_evaluation_summary_v1"

#: The Task-7 approximation-bias fairness CARRY key + its exact inner roster (design
#: spec §5/§7). The finalizer only ASSERTS the block's PRESENCE and shape (fail closed
#: if a summary-bearing terminal omits it) — it NEVER populates or mutates it: the block
#: is built ONCE at phase2b BUILD time before ``registered_summary_checksum`` and copied
#: verbatim here. Mirrored (not imported) because ``phase2b`` imports this module, so
#: importing back would be circular; the constants are kept byte-identical by design.
_APPROXIMATION_BIAS_FAIRNESS_KEY = "approximation_bias_fairness"
_APPROXIMATION_BIAS_FAIRNESS_FIELDS: frozenset[str] = frozenset(
    {
        "report_sha256",
        "fairness_flag",
        "bias_to_signal_ratio_R",
        "bootstrap_95_interval",
        "R_star",
    }
)

#: The marker's self-excluding checksum field (excluded from its own checksum).
COMMIT_CHECKSUM_FIELD = "commit_checksum"

#: Terminal filename -> the terminal state it must carry (the roster the finalizer
#: independently scans and validates; shared with the terminal writer's constants).
_TERMINAL_FILENAME_STATE: dict[str, TerminalState] = {
    Phase2bTerminal.COMPLETE_ARTIFACT: TerminalState.COMPLETE,
    Phase2bTerminal.INVALID_ARTIFACT: TerminalState.INVALID,
    Phase2bTerminal.ABORTED_ARTIFACT: TerminalState.ABORTED_AFTER_SEAL,
}
_TERMINAL_FILENAMES: frozenset[str] = frozenset(_TERMINAL_FILENAME_STATE)

#: Terminal states that carry a ``registered_summary`` + embedded provenance and are
#: therefore published via the FULL forward path (spec §2.1). An
#: ``ABORTED_AFTER_SEAL`` terminal carries no registered summary and no embedded
#: provenance; the finalizer branches to the REDUCED abort publish
#: (:func:`_finalize_aborted_terminal`) for it (spec §3.3) rather than refusing.
_SUMMARY_BEARING_STATES: frozenset[TerminalState] = frozenset(
    {TerminalState.COMPLETE, TerminalState.INVALID}
)


class DurableLedgerError(RuntimeError):
    """Raised on any durable-finalize integrity, path-safety or write-once failure.

    Distinct from the terminal / provenance error types: this guards the DERIVED
    durable publish (registered summary, final ledger, commit marker), never the
    seal or the terminal artifact itself. Every failure leaves the sealed terminal
    untouched; the absence of the commit marker signals an incomplete export.
    """


@dataclass(frozen=True)
class DurableFinalizeResult:
    """Outcome of a successful durable finalize (spec §3.1).

    Attributes
    ----------
    run_dir : Path
        The resolved run directory holding every terminal and derived artifact.
    terminal_state : str
        The verified terminal state value (``"COMPLETE"`` / ``"INVALID"`` /
        ``"ABORTED_AFTER_SEAL"``).
    terminal_path : Path
        The resolved single sealed terminal artifact (the recovery source).
    registered_summary_path : Path or None
        The published outcome-free registered summary for a summary-bearing
        (``COMPLETE`` / ``INVALID``) terminal; ``None`` on the reduced abort path
        (an ``ABORTED_AFTER_SEAL`` terminal carries no registered summary, so none
        is published).
    final_ledger_path : Path
        The published final ledger (pre-access snapshot + expanded provenance +
        write-once file-SHA entries; the abort path records only the {terminal,
        seed} file SHAs over the pre-access snapshot).
    commit_marker_path : Path
        The single durable commit marker installed LAST.
    commit_checksum : str
        The marker's self-excluding ``commit_checksum``.
    """

    run_dir: Path
    terminal_state: str
    terminal_path: Path
    registered_summary_path: Path | None
    final_ledger_path: Path
    commit_marker_path: Path
    commit_checksum: str


def _canonical_bytes(obj: object) -> bytes:
    """Canonical JSON bytes (``sort_keys`` + compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _file_sha(path: Path) -> str:
    """SHA-256 hex of a file's raw bytes (the durable file-SHA convention)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install_or_verify_exact(path: str | Path, intended_bytes: str) -> None:
    """Idempotently install ``intended_bytes`` at ``path`` (spec §3.2).

    - Absent destination: atomic write-once install.
    - Present and byte-identical (and SHA-identical): a no-op — never rewritten.
    - Present and DIFFERENT: :class:`DurableLedgerError` (permanent; a durable
      output is never overwritten once installed).

    Routing every durable install through this makes the forward publish and the
    recovery path idempotent: re-running with byte-identical content over an
    already-installed file succeeds without a write, so a crash-interrupted publish
    can be safely re-driven, while any content divergence fails closed.

    Parameters
    ----------
    path : str or Path
        Destination durable output path.
    intended_bytes : str
        The exact text the file must carry (UTF-8 encoded).

    Raises
    ------
    DurableLedgerError
        If a pre-existing file's bytes/SHA differ from ``intended_bytes``, or the
        atomic install otherwise fails.
    """
    destination = Path(path)
    intended_encoded = intended_bytes.encode("utf-8")
    intended_sha = hashlib.sha256(intended_encoded).hexdigest()
    try:
        existing = destination.read_bytes()
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise DurableLedgerError(
            f"durable output {str(destination)!r} could not be read for verification: {exc}"
        ) from exc
    if existing is not None:
        if existing != intended_encoded or hashlib.sha256(existing).hexdigest() != intended_sha:
            raise DurableLedgerError(
                f"durable output {str(destination)!r} already exists with DIFFERENT "
                "content; durable outputs are never overwritten (permanent failure)."
            )
        return  # present & byte/SHA-identical -> idempotent no-op
    try:
        atomic_write_once(destination, intended_bytes)
    except FileExistsError as exc:
        # Lost a create race: re-verify the winner is byte-identical (else fail closed).
        try:
            winner = destination.read_bytes()
        except OSError as read_exc:  # pragma: no cover - unreadable right after link
            raise DurableLedgerError(
                f"durable output {str(destination)!r} appeared but is unreadable: {read_exc}"
            ) from read_exc
        if winner != intended_encoded:
            raise DurableLedgerError(
                f"durable output {str(destination)!r} was concurrently created with "
                "DIFFERENT content (permanent failure)."
            ) from exc
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise DurableLedgerError(
            f"failed to install durable output {str(destination)!r}: {exc}"
        ) from exc


def _resolve_regular_child(
    path: str | Path, *, run_dir: Path, allowed: frozenset[str] | set[str]
) -> Path:
    """Resolve ``path`` and require a REGULAR FILE that is a direct child of ``run_dir``.

    Fails closed on a symlink (final component), a directory / device / FIFO, a
    path outside ``run_dir``, or a filename outside ``allowed`` (spec §3). Uses
    :func:`os.stat` + :data:`stat.S_ISREG` (not :meth:`Path.is_file`, which
    follows symlinks) and rejects :meth:`Path.is_symlink` on the pre-resolve path.

    Parameters
    ----------
    path : str or Path
        Candidate input path.
    run_dir : Path
        Already-resolved run directory the file must be a direct child of.
    allowed : set of str
        The exact filename roster the basename must belong to.

    Returns
    -------
    Path
        The resolved path (its ``.name`` is in ``allowed``).

    Raises
    ------
    DurableLedgerError
        On any path-safety or roster violation.
    """
    candidate = Path(path)
    if candidate.is_symlink():
        raise DurableLedgerError(
            f"input path {str(candidate)!r} is a symlink; durable inputs must be "
            "regular files (fail closed)."
        )
    try:
        st = os.stat(candidate)
    except OSError as exc:
        raise DurableLedgerError(
            f"input path {str(candidate)!r} could not be stat-ed: {exc}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise DurableLedgerError(
            f"input path {str(candidate)!r} is not a regular file "
            "(directory / device / FIFO rejected)."
        )
    resolved = candidate.resolve()
    if resolved.parent != run_dir:
        raise DurableLedgerError(
            f"input path {str(resolved)!r} is not a direct child of run_dir {str(run_dir)!r}."
        )
    if resolved.name not in allowed:
        raise DurableLedgerError(
            f"input filename {resolved.name!r} is not in the allowed roster {sorted(allowed)!r}."
        )
    return resolved


def _resolve_run_dir(run_dir: str | Path) -> Path:
    """Resolve ``run_dir``, requiring a real (non-symlink) directory (spec §3).

    Raises
    ------
    DurableLedgerError
        If ``run_dir`` is a symlink, inaccessible, or not a directory.
    """
    run_dir_path = Path(run_dir)
    if run_dir_path.is_symlink():
        raise DurableLedgerError(f"run_dir {str(run_dir_path)!r} is a symlink; refused.")
    try:
        run_st = os.stat(run_dir_path)
    except OSError as exc:
        raise DurableLedgerError(f"run_dir {str(run_dir_path)!r} is not accessible: {exc}") from exc
    if not stat.S_ISDIR(run_st.st_mode):
        raise DurableLedgerError(f"run_dir {str(run_dir_path)!r} is not a directory.")
    return run_dir_path.resolve()


def _scan_terminals(run_dir_resolved: Path) -> list[str]:
    """Independently scan ``run_dir`` for terminal artifacts (0, 1 or more; spec §3).

    Iterates the fixed terminal-filename roster, refusing a symlink at any roster
    name, and returns the roster names present as regular files (in sorted-roster
    order). The finalizer/recovery never trusts a caller-supplied path alone.

    Raises
    ------
    DurableLedgerError
        On a terminal-named symlink or an un-stat-able candidate.
    """
    scanned: list[str] = []
    for name in sorted(_TERMINAL_FILENAMES):
        candidate = run_dir_resolved / name
        if candidate.is_symlink():
            raise DurableLedgerError(
                f"a terminal-named path {str(candidate)!r} is a symlink; refused."
            )
        try:
            cst = os.stat(candidate)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DurableLedgerError(
                f"terminal candidate {str(candidate)!r} could not be stat-ed: {exc}"
            ) from exc
        if stat.S_ISREG(cst.st_mode):
            scanned.append(name)
    return scanned


def _scan_single_terminal(run_dir_resolved: Path) -> str:
    """Independently scan ``run_dir`` for EXACTLY ONE terminal artifact (spec §3).

    Thin wrapper over :func:`_scan_terminals` enforcing a count of exactly 1 and
    returning the sole terminal filename. 0 or ≥2 terminals fail closed.

    Raises
    ------
    DurableLedgerError
        On a terminal-named symlink, an un-stat-able candidate, or a count != 1.
    """
    scanned = _scan_terminals(run_dir_resolved)
    if len(scanned) != 1:
        raise DurableLedgerError(
            f"expected EXACTLY ONE terminal artifact in {str(run_dir_resolved)!r}; "
            f"found {scanned!r} (fail closed)."
        )
    return scanned[0]


def _expand_embedded_provenance(embedded: dict) -> dict[str, str]:
    """Expand the terminal's embedded provenance into individual canonical entries.

    Reuses the SAME field->artifact-name mapping the pre-access recorder uses
    (:data:`~alive.compose.provenance2._DIGEST_ARTIFACTS` /
    :data:`~alive.compose.provenance2._EVIDENCE_ARTIFACTS`) so the final ledger
    entries line up byte-for-byte with how provenance digests are named elsewhere
    (never a second, divergent mapping). Digest fields are recorded verbatim;
    evidence fields are recorded as ``sha256_json(value)`` — exactly
    :func:`~alive.compose.provenance2.record_phase2b_provenance`.

    Raises
    ------
    DurableLedgerError
        If a mapped provenance field is absent from the embedded payload.
    """
    expanded: dict[str, str] = {}
    for name, field in _DIGEST_ARTIFACTS:
        if field not in embedded:
            raise DurableLedgerError(
                f"terminal embedded provenance is missing digest field {field!r}."
            )
        expanded[name] = embedded[field]
    for name, field in _EVIDENCE_ARTIFACTS:
        if field not in embedded:
            raise DurableLedgerError(
                f"terminal embedded provenance is missing evidence field {field!r}."
            )
        expanded[name] = sha256_json(embedded[field])
    return expanded


#: The seed-variability report's self-excluding checksum key, matching exactly the
#: key ``development_seed_variability`` writes in
#: :mod:`alive.compose.seed_variability` (``report_checksum ==
#: sha256_json(payload_without_report_checksum)``; see ``SeedVariabilityReport``).
_SEED_REPORT_CHECKSUM_KEY = "report_checksum"


def _read_seed_report_checksum(path: Path) -> str:
    """Extract + validate the seed report's self-excluding ``report_checksum`` (M1).

    Beyond checking the field is a non-empty string, this recomputes the seed
    report's self-excluding self-checksum EXACTLY as
    :func:`~alive.compose.seed_variability.development_seed_variability` derives it —
    ``sha256_json`` over the whole document MINUS the ``report_checksum`` key — and
    fails closed on any mismatch (a tampered seed body is rejected regardless of its
    byte SHA agreeing elsewhere).
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} is not readable JSON: {exc}"
        ) from exc
    if not isinstance(doc, dict) or _SEED_REPORT_CHECKSUM_KEY not in doc:
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} lacks a {_SEED_REPORT_CHECKSUM_KEY!r} field."
        )
    checksum = doc[_SEED_REPORT_CHECKSUM_KEY]
    if not isinstance(checksum, str) or not checksum.strip():
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} carries an empty {_SEED_REPORT_CHECKSUM_KEY}."
        )
    payload_without_checksum = {
        key: value for key, value in doc.items() if key != _SEED_REPORT_CHECKSUM_KEY
    }
    if sha256_json(payload_without_checksum) != checksum:
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} self-checksum does not bind its "
            "payload (report_checksum != sha256_json(payload_without_report_checksum))."
        )
    return checksum


def _finalize_aborted_terminal(
    *,
    run_dir_resolved: Path,
    terminal_resolved: Path,
    terminal_body: dict,
    run_id: str,
    terminal_state: TerminalState,
    pre_access_resolved: Path,
    seed_resolved: Path,
) -> DurableFinalizeResult:
    """Publish the REDUCED durable set for an ``ABORTED_AFTER_SEAL`` terminal (spec §3.3).

    An aborted terminal carries NO ``registered_summary`` and NO
    ``terminal_embedded_provenance``, so — unlike the summary-bearing path — this
    derives all provenance from the PRE-ACCESS LEDGER snapshot (never the terminal).
    It SKIPS ``phase2b_registered_summary.json``, builds
    ``phase2b_final_ledger.json`` as the pre-access snapshot PLUS write-once
    file-SHA entries for the {terminal, seed_variability} pair ONLY (the pre-access
    snapshot already holds the pre-access provenance subset), and installs the
    ``phase2b_durable_commit.json`` marker LAST with a DETERMINISTIC field set that
    omits every registered-summary field. Because the field set is fixed for the
    abort state and every value is deterministic canonical JSON / a file SHA, a
    byte-identical re-derivation reproduces the SAME marker (idempotent recovery).

    The caller has ALREADY run the shared terminal verification (path safety,
    single-terminal scan, canonical JSON, exact ABORTED roster, run id, and the
    whole-body ``terminal_payload_checksum`` via the shared canonicalizer). Opens
    NO seal and constructs NO outcome store.

    Parameters
    ----------
    run_dir_resolved : Path
        The already-resolved run directory.
    terminal_resolved : Path
        The already-resolved ``ABORTED_AFTER_SEAL`` terminal artifact.
    terminal_body : dict
        The already-verified decoded terminal body (carrying the two pre-access
        identity anchors used for the non-circular binding).
    run_id : str
        The verified non-empty terminal run id.
    terminal_state : TerminalState
        ``TerminalState.ABORTED_AFTER_SEAL`` (its ``.value`` is bound into the marker).
    pre_access_resolved, seed_resolved : Path
        The already-resolved pre-access ledger snapshot and seed-variability report.

    Returns
    -------
    DurableFinalizeResult
        The verified reduced publish (``registered_summary_path`` is ``None``).

    Raises
    ------
    DurableLedgerError
        On any pre-access binding, seed cross-check, write-once, or
        re-verification failure. The sealed terminal is left untouched.
    """
    # --- Read + verify the pre-access ledger: run id, the persisted pre-access
    # provenance subset checksum, and the non-circular binding. The abort terminal
    # has NO embedded provenance, so the binding runs against the abort terminal's
    # OWN pre-access identity anchors (the terminal roster proved them non-empty),
    # never a terminal-embedded provenance payload.
    try:
        pre_access_ledger = RunLedger.read(pre_access_resolved)
    except LedgerError as exc:
        raise DurableLedgerError(
            f"pre-access ledger {str(pre_access_resolved)!r} is not a valid ledger: {exc}"
        ) from exc
    pre_access_dict = pre_access_ledger.to_dict()
    if pre_access_dict.get("run_id") != run_id:
        raise DurableLedgerError(
            f"pre-access ledger run_id {pre_access_dict.get('run_id')!r} disagrees with "
            f"the terminal run_id {run_id!r}."
        )
    try:
        recorded_pre_access_checksum = pre_access_ledger.artifact_sha(
            PRE_ACCESS_PROVENANCE_ARTIFACT
        )
    except LedgerError as exc:
        raise DurableLedgerError(
            "pre-access ledger is missing the pre-access provenance subset checksum "
            f"{PRE_ACCESS_PROVENANCE_ARTIFACT!r}: {exc}"
        ) from exc
    if terminal_body["pre_access_provenance_checksum"] != recorded_pre_access_checksum:
        raise DurableLedgerError(
            "the aborted terminal's pre_access_provenance_checksum does not match the "
            "persisted pre-access ledger subset checksum (non-circular binding broken)."
        )
    pre_access_sha = _file_sha(pre_access_resolved)
    if terminal_body["pre_access_ledger_sha256"] != pre_access_sha:
        raise DurableLedgerError(
            "the aborted terminal's pre_access_ledger_sha256 does not match the on-disk "
            "pre-access ledger file SHA (the pre-access snapshot was modified)."
        )

    pre_access_artifacts = {rec["name"]: rec["sha256"] for rec in pre_access_dict["artifacts"]}

    # --- Build phase2b_final_ledger.json = pre-access snapshot + write-once file-SHA
    # entries for {terminal, seed} ONLY. No summary entry and no expanded
    # terminal-embedded provenance (there is none): the pre-access snapshot already
    # carries the pre-access provenance subset. It NEVER records the marker or itself.
    final_ledger = RunLedger.read(pre_access_resolved)
    terminal_sha = _file_sha(terminal_resolved)
    seed_sha = _file_sha(seed_resolved)

    # The seed-variability file the pre-access ledger digested must be byte-stable.
    if "development_seed_variability" in pre_access_artifacts and (
        pre_access_artifacts["development_seed_variability"] != seed_sha
    ):
        raise DurableLedgerError(
            "the seed-variability file SHA disagrees with the digest recorded in the "
            "pre-access ledger (the durable report was modified after binding)."
        )

    try:
        final_ledger.record_artifact(terminal_resolved.name, terminal_sha)
        final_ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_FILENAME, seed_sha)
    except DuplicateArtifactError as exc:
        raise DurableLedgerError(
            f"write-once violation assembling the abort final ledger: {exc}"
        ) from exc
    final_ledger_bytes = _canonical_bytes(final_ledger.to_dict())
    final_ledger_sha = hashlib.sha256(final_ledger_bytes).hexdigest()
    final_ledger_path = run_dir_resolved / FINAL_LEDGER_FILENAME
    install_or_verify_exact(final_ledger_path, final_ledger_bytes.decode("utf-8"))

    # Re-read the final ledger and compare to the intended canonical bytes + SHA.
    if (
        final_ledger_path.read_bytes() != final_ledger_bytes
        or _file_sha(final_ledger_path) != final_ledger_sha
    ):
        raise DurableLedgerError(
            "published abort final ledger failed post-install re-verification."
        )

    # --- Install phase2b_durable_commit.json LAST. The abort marker's field set is
    # DETERMINISTIC for the abort state (NO registered_summary fields), so recovery
    # re-derives it byte-identically. It binds the final ledger EXTERNALLY.
    seed_self_checksum = _read_seed_report_checksum(seed_resolved)
    marker_core = {
        "schema": DURABLE_COMMIT_SCHEMA,
        "protocol": terminal_body["protocol"],
        "run_id": run_id,
        "terminal_state": terminal_state.value,
        "terminal": {"filename": terminal_resolved.name, "sha256": terminal_sha},
        "final_ledger": {"filename": FINAL_LEDGER_FILENAME, "sha256": final_ledger_sha},
        "pre_access_ledger": {"filename": PRE_ACCESS_LEDGER_FILENAME, "sha256": pre_access_sha},
        "seed_variability": {
            "filename": DEVELOPMENT_SEED_VARIABILITY_FILENAME,
            "sha256": seed_sha,
            "self_checksum": seed_self_checksum,
        },
    }
    commit_checksum = sha256_json(marker_core)
    marker = {**marker_core, COMMIT_CHECKSUM_FIELD: commit_checksum}
    marker_bytes = _canonical_bytes(marker)
    marker_path = run_dir_resolved / DURABLE_COMMIT_FILENAME
    install_or_verify_exact(marker_path, marker_bytes.decode("utf-8"))

    # Re-read the marker and re-verify self-checksum, every recorded file SHA, and
    # run id / state.
    marker_raw = marker_path.read_bytes()
    try:
        reloaded = json.loads(marker_raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - just installed
        raise DurableLedgerError(f"abort commit marker re-read is not valid JSON: {exc}") from exc
    if marker_raw != _canonical_bytes(reloaded):
        raise DurableLedgerError("abort commit marker re-read is not canonical JSON.")
    reloaded_core = {k: v for k, v in reloaded.items() if k != COMMIT_CHECKSUM_FIELD}
    if sha256_json(reloaded_core) != reloaded.get(COMMIT_CHECKSUM_FIELD):
        raise DurableLedgerError("abort commit marker self-checksum failed re-verification.")
    if reloaded.get("run_id") != run_id or reloaded.get("terminal_state") != terminal_state.value:
        raise DurableLedgerError(
            "abort commit marker run_id / terminal_state failed re-verification."
        )
    file_sha_checks = (
        (terminal_resolved, reloaded["terminal"]["sha256"]),
        (final_ledger_path, reloaded["final_ledger"]["sha256"]),
        (pre_access_resolved, reloaded["pre_access_ledger"]["sha256"]),
        (seed_resolved, reloaded["seed_variability"]["sha256"]),
    )
    for path, expected_sha in file_sha_checks:
        if _file_sha(path) != expected_sha:
            raise DurableLedgerError(
                f"abort commit marker file-SHA for {str(path)!r} failed re-verification."
            )

    return DurableFinalizeResult(
        run_dir=run_dir_resolved,
        terminal_state=terminal_state.value,
        terminal_path=terminal_resolved,
        registered_summary_path=None,
        final_ledger_path=final_ledger_path,
        commit_marker_path=marker_path,
        commit_checksum=commit_checksum,
    )


def finalize_phase2b_durable_outputs(
    *,
    run_dir: str | Path,
    terminal_path: str | Path,
    pre_access_ledger_path: str | Path,
    seed_variability_path: str | Path,
) -> DurableFinalizeResult:
    """Publish the durable derived outputs from an already-written sealed terminal.

    Reads the sealed terminal, the persisted pre-access ledger snapshot and the D2
    seed-variability report; publishes ``phase2b_registered_summary.json``,
    ``phase2b_final_ledger.json`` and finally ``phase2b_durable_commit.json`` (the
    marker installed LAST), following the exact publish order of spec §3.1. A
    summary-bearing (``COMPLETE`` / ``INVALID``) terminal takes the full path; an
    ``ABORTED_AFTER_SEAL`` terminal — which carries no registered summary and no
    embedded provenance — branches to the REDUCED abort publish
    (:func:`_finalize_aborted_terminal`, spec §3.3): no registered summary file, a
    final ledger over the pre-access snapshot binding only the {terminal, seed}
    file SHAs, and a marker whose deterministic field set omits every summary field.
    Opens NO seal and constructs NO outcome store.

    Parameters
    ----------
    run_dir : str or Path
        The run directory; every input and derived file must be a direct child.
    terminal_path : str or Path
        The single sealed terminal artifact (``COMPLETE`` / ``INVALID`` /
        ``ABORTED_AFTER_SEAL``).
    pre_access_ledger_path : str or Path
        The persisted pre-access ledger snapshot (``phase2b_pre_access_ledger.json``).
    seed_variability_path : str or Path
        The D2 development seed-variability report (``development_seed_variability.json``).

    Returns
    -------
    DurableFinalizeResult
        The verified publish result (paths + terminal state + commit checksum).

    Raises
    ------
    DurableLedgerError
        On any path-safety, roster, checksum, cross-check, write-once or
        re-verification failure. Every failure leaves the sealed terminal
        untouched; the marker's absence marks an incomplete durable export.
    """
    # --- Path safety (spec §3): run_dir a directory, every input a regular-file
    # direct child of it, with a roster-exact filename.
    run_dir_resolved = _resolve_run_dir(run_dir)

    terminal_resolved = _resolve_regular_child(
        terminal_path, run_dir=run_dir_resolved, allowed=_TERMINAL_FILENAMES
    )
    pre_access_resolved = _resolve_regular_child(
        pre_access_ledger_path, run_dir=run_dir_resolved, allowed={PRE_ACCESS_LEDGER_FILENAME}
    )
    seed_resolved = _resolve_regular_child(
        seed_variability_path,
        run_dir=run_dir_resolved,
        allowed={DEVELOPMENT_SEED_VARIABILITY_FILENAME},
    )

    # --- Independent scan: EXACTLY ONE terminal file (0 or >=2 fail closed). The
    # finalizer never trusts the caller-supplied path alone (spec §3).
    scanned_name = _scan_single_terminal(run_dir_resolved)
    if scanned_name != terminal_resolved.name:
        raise DurableLedgerError(
            f"caller terminal {terminal_resolved.name!r} disagrees with the sole "
            f"terminal on disk {scanned_name!r}."
        )
    terminal_state = _TERMINAL_FILENAME_STATE[terminal_resolved.name]

    # --- Step 1: read + verify the terminal (canonical JSON, exact roster, run id,
    # and the whole-body terminal_payload_checksum via the SHARED canonicalizer).
    terminal_raw = terminal_resolved.read_bytes()
    try:
        terminal_body = json.loads(terminal_raw)
    except json.JSONDecodeError as exc:
        raise DurableLedgerError(
            f"terminal {str(terminal_resolved)!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(terminal_body, dict):
        raise DurableLedgerError(f"terminal {str(terminal_resolved)!r} is not a JSON object.")
    if terminal_raw != _canonical_bytes(terminal_body):
        raise DurableLedgerError(
            f"terminal {str(terminal_resolved)!r} is not canonical JSON "
            "(sorted keys, compact separators)."
        )
    expected_keys = (
        set(_COMMON_TERMINAL_FIELDS)
        | set(_STATE_TERMINAL_FIELDS[terminal_state])
        | {TERMINAL_PAYLOAD_CHECKSUM_FIELD}
    )
    if set(terminal_body) != expected_keys:
        raise DurableLedgerError(
            f"terminal {str(terminal_resolved)!r} roster mismatch for state "
            f"{terminal_state.value!r}: unexpected "
            f"{sorted(set(terminal_body) - expected_keys)!r}, missing "
            f"{sorted(expected_keys - set(terminal_body))!r}."
        )
    if terminal_body.get("terminal_state") != terminal_state.value:
        raise DurableLedgerError(
            f"terminal filename {terminal_resolved.name!r} and body terminal_state "
            f"{terminal_body.get('terminal_state')!r} disagree."
        )
    run_id = terminal_body.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise DurableLedgerError("terminal carries an empty run_id (un-attributable).")

    # LANDMINE: the whole-body checksum was produced by the terminal writer via
    # canonicalize_terminal_checksum_input (finite floats -> float.hex()). Verify it
    # the SAME way; a raw sha256_json over the decoded body would reject every real
    # terminal that carries a float in its registered_summary.
    claimed_payload_checksum = terminal_body[TERMINAL_PAYLOAD_CHECKSUM_FIELD]
    body_without_checksum = {
        key: value for key, value in terminal_body.items() if key != TERMINAL_PAYLOAD_CHECKSUM_FIELD
    }
    try:
        recomputed_payload_checksum = sha256_json(
            canonicalize_terminal_checksum_input(body_without_checksum)
        )
    except Exception as exc:
        raise DurableLedgerError(
            f"terminal {str(terminal_resolved)!r} payload could not be canonicalised: {exc}"
        ) from exc
    if recomputed_payload_checksum != claimed_payload_checksum:
        raise DurableLedgerError(
            f"terminal {str(terminal_resolved)!r} terminal_payload_checksum mismatch "
            "(recomputed via the shared canonicalizer)."
        )

    # --- Branch: an ABORTED_AFTER_SEAL terminal carries NO registered_summary and NO
    # embedded provenance (spec §3.3), so it takes the REDUCED abort publish, which
    # derives provenance from the pre-access ledger snapshot, not the terminal. The
    # shared verification above (path safety, single-terminal scan, canonical JSON,
    # exact roster, run id and the whole-body payload checksum) has already run.
    if terminal_state not in _SUMMARY_BEARING_STATES:
        return _finalize_aborted_terminal(
            run_dir_resolved=run_dir_resolved,
            terminal_resolved=terminal_resolved,
            terminal_body=terminal_body,
            run_id=run_id,
            terminal_state=terminal_state,
            pre_access_resolved=pre_access_resolved,
            seed_resolved=seed_resolved,
        )

    # Inner content checksums the finalizer directly consumes (these ARE sha256_json
    # over their own dicts — verify as-is).
    registered_summary = terminal_body["registered_summary"]
    registered_summary_checksum = terminal_body["registered_summary_checksum"]
    if sha256_json(registered_summary) != registered_summary_checksum:
        raise DurableLedgerError("terminal registered_summary_checksum does not bind its summary.")
    embedded = terminal_body["terminal_embedded_provenance"]
    if not isinstance(embedded, dict):
        raise DurableLedgerError("terminal embedded provenance is not a JSON object.")
    if sha256_json(embedded) != terminal_body["provenance_checksum"]:
        raise DurableLedgerError("terminal provenance_checksum does not bind its embedded payload.")

    # --- Recompute final_result_checksum from its 5 constituent identity fields —
    # all top-level body keys, binding EXACTLY these five (phase2b.py:1620-1628). The
    # whole-body terminal_payload_checksum above only catches POST-hoc tampering; a
    # writer that emits a self-consistent-but-WRONG final_result_checksum at write time
    # (its whole-body checksum happily binds the wrong value) is caught only here.
    # sha256_json sorts keys, so this dict's insertion order is irrelevant.
    recomputed_final_result_checksum = sha256_json(
        {
            "terminal_state": terminal_body["terminal_state"],
            "final_verdict_checksum": terminal_body["final_verdict_checksum"],
            "registered_summary_checksum": terminal_body["registered_summary_checksum"],
            "evaluation_payload_checksum": terminal_body["evaluation_payload_checksum"],
            "provenance_checksum": terminal_body["provenance_checksum"],
        }
    )
    if recomputed_final_result_checksum != terminal_body["final_result_checksum"]:
        raise DurableLedgerError(
            "terminal final_result_checksum does not match its 5 constituent identity "
            "fields (terminal_state, final_verdict_checksum, registered_summary_checksum, "
            "evaluation_payload_checksum, provenance_checksum); fail closed."
        )
    # --- Amendment B (signed 2026-09-05): the descriptive-only band-sensitivity block
    # rides OUTSIDE the five identity fields with its own checksum. Same
    # defense-in-depth as above: the whole-body checksum catches post-hoc tampering; a
    # writer that emits a block and a checksum that disagree is caught only here.
    sensitivity_block = terminal_body.get("band_sensitivity")
    if not isinstance(sensitivity_block, dict) or (
        sha256_json(sensitivity_block) != terminal_body.get("band_sensitivity_checksum")
    ):
        raise DurableLedgerError(
            "terminal band_sensitivity_checksum does not bind its band_sensitivity block "
            "(sha256_json(block) != band_sensitivity_checksum); fail closed."
        )

    # --- 2026-09-09: since `compose_band_sensitivity_v2` the block CARRIES the
    # pre-registered D4 §8 headline sentence, and the binding above is not enough for it.
    # A checksum binds the block to the terminal; it says nothing about whether the
    # sentence is the one the result SELECTS. A writer that emits a self-consistent but
    # WRONG sentence -- a branch the flip contradicts, an un-substituted `<flip>`, the
    # learned-family sentence on an axis that never earned it -- passed every check this
    # finalizer had (measured: all five published). So the sentence is RE-DERIVED here from
    # the terminal's own verdict fields and the block's own ladder, and must match exactly.
    verdict_clauses = registered_summary.get("verdict_clauses")
    if not isinstance(verdict_clauses, dict) or "additive_clears" not in verdict_clauses:
        raise DurableLedgerError(
            "registered summary verdict_clauses is missing or carries no 'additive_clears' "
            "clause, so band_sensitivity.headline cannot be re-derived; fail closed."
        )
    by_lambda = sensitivity_block.get("by_lambda")
    if not isinstance(by_lambda, list) or not by_lambda:
        raise DurableLedgerError(
            "terminal band_sensitivity.by_lambda is missing or empty, so the registered "
            "ladder maximum band_sensitivity.headline needs is unknown; fail closed."
        )
    try:
        ladder_max = max(float(entry["lambda"]) for entry in by_lambda)
        flip = sensitivity_block["flip_lambda"]["additive"]
        sealed_axis = str(registered_summary["sealed_axis"])
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DurableLedgerError(
            "terminal band_sensitivity/registered_summary does not carry the fields "
            f"band_sensitivity.headline is derived from ({exc}); fail closed."
        ) from exc
    # The renderer accepts a label or a number; anything else would reach `float()` inside
    # it as an untyped crash, so it is refused here instead.
    if isinstance(flip, bool) or not isinstance(flip, (str, int, float)):
        raise DurableLedgerError(
            f"terminal band_sensitivity.flip_lambda['additive'] is {type(flip).__name__}, "
            "neither a registered label nor a number; fail closed."
        )
    expected_headline = render_preregistered_headline(
        band_passes=bool(verdict_clauses["additive_clears"]),
        flip=flip,
        ladder_max=ladder_max,
        sealed_axis=sealed_axis,
    )
    headline = sensitivity_block.get("headline")
    if headline != expected_headline:
        raise DurableLedgerError(
            "terminal band_sensitivity.headline is not the pre-registered sentence its own "
            f"result selects: re-derived from sealed_axis={sealed_axis!r}, "
            f"verdict_clauses.additive_clears={bool(verdict_clauses['additive_clears'])!r}, "
            f"flip_lambda['additive']={flip!r} and ladder_max={ladder_max!r}, the block "
            "carries a different one (D4 §8); fail closed."
        )
    # The renderer RECORDS an unreachable (band_passes, flip) pair rather than raising, so a
    # legitimate terminal write is never aborted by a diagnostic. Publishing it as a durable
    # artifact is the other question, and the answer is no: a marker is a bug report.
    if headline.get("inconsistent") is True:
        raise DurableLedgerError(
            "terminal band_sensitivity.headline carries the inconsistent marker "
            f"(inconsistent: true, reason: {headline.get('reason')!r}); the result's band "
            "verdict and flip point cannot both hold, so no pre-registered sentence "
            "applies and this is not a publishable artifact; fail closed."
        )

    # --- Validate the registered-summary schema + method/comparator rosters (Task 5
    # v1 shape). A wrong schema, a per-method-MSE roster != the 9-method roster (in
    # either regime), or a theta roster != the 5-comparator family fails closed.
    if registered_summary.get("schema") != _REGISTERED_SUMMARY_SCHEMA_V1:
        raise DurableLedgerError(
            f"registered summary schema {registered_summary.get('schema')!r} is not the "
            f"expected {_REGISTERED_SUMMARY_SCHEMA_V1!r} (fail closed)."
        )
    per_method_aggregate_mse = registered_summary.get("per_method_aggregate_mse")
    if not isinstance(per_method_aggregate_mse, dict):
        raise DurableLedgerError(
            "registered summary per_method_aggregate_mse is not a JSON object (fail closed)."
        )
    for regime in ("double", "single"):
        regime_mse = per_method_aggregate_mse.get(regime)
        if not isinstance(regime_mse, dict):
            raise DurableLedgerError(
                f"registered summary per_method_aggregate_mse[{regime!r}] is missing or is "
                "not a JSON object (fail closed)."
            )
        got_methods = set(regime_mse)
        if got_methods != set(_EXPECTED_METHOD_ROSTER):
            raise DurableLedgerError(
                f"registered summary per_method_aggregate_mse[{regime!r}] method roster "
                f"{sorted(got_methods)!r} != the expected 9-method roster "
                f"{sorted(_EXPECTED_METHOD_ROSTER)!r} (fail closed)."
            )
    theta = registered_summary.get("theta")
    if not isinstance(theta, dict):
        raise DurableLedgerError("registered summary theta is not a JSON object (fail closed).")
    theta_roster = set(theta)
    if theta_roster != set(_EXPECTED_COMPARATOR_FAMILY):
        raise DurableLedgerError(
            f"registered summary theta roster {sorted(theta_roster)!r} != the expected "
            f"5-comparator family {sorted(_EXPECTED_COMPARATOR_FAMILY)!r} (fail closed)."
        )

    # --- Task 7 (spec §5/§7): the pre-registered approximation-bias fairness CARRY must
    # be PRESENT with its exact inner roster. This is a PRESENCE/shape assertion ONLY —
    # the block is built ONCE at phase2b BUILD time (before registered_summary_checksum)
    # and copied VERBATIM below; the finalizer NEVER populates or mutates it. A
    # summary-bearing terminal that omits it (or carries a wrong-shaped block) fails
    # closed so the verdict-invariant disclosure can never be silently dropped.
    fairness = registered_summary.get(_APPROXIMATION_BIAS_FAIRNESS_KEY)
    if not isinstance(fairness, dict):
        raise DurableLedgerError(
            f"registered summary is missing the {_APPROXIMATION_BIAS_FAIRNESS_KEY!r} carry "
            "or it is not a JSON object (fail closed)."
        )
    if set(fairness) != _APPROXIMATION_BIAS_FAIRNESS_FIELDS:
        raise DurableLedgerError(
            f"registered summary {_APPROXIMATION_BIAS_FAIRNESS_KEY!r} roster {sorted(fairness)!r} "
            f"!= the expected fields {sorted(_APPROXIMATION_BIAS_FAIRNESS_FIELDS)!r} (fail closed)."
        )

    # --- Step 2: read + verify the pre-access ledger (run id, embedded pre-access
    # provenance subset checksum, and shared upstream digests vs the terminal's
    # embedded provenance). The subset binding is the NON-CIRCULAR link (spec §1.1).
    try:
        pre_access_ledger = RunLedger.read(pre_access_resolved)
    except LedgerError as exc:
        raise DurableLedgerError(
            f"pre-access ledger {str(pre_access_resolved)!r} is not a valid ledger: {exc}"
        ) from exc
    pre_access_dict = pre_access_ledger.to_dict()
    if pre_access_dict.get("run_id") != run_id:
        raise DurableLedgerError(
            f"pre-access ledger run_id {pre_access_dict.get('run_id')!r} disagrees with "
            f"the terminal run_id {run_id!r}."
        )
    try:
        recorded_pre_access_checksum = pre_access_ledger.artifact_sha(
            PRE_ACCESS_PROVENANCE_ARTIFACT
        )
    except LedgerError as exc:
        raise DurableLedgerError(
            "pre-access ledger is missing the pre-access provenance subset checksum "
            f"{PRE_ACCESS_PROVENANCE_ARTIFACT!r}: {exc}"
        ) from exc
    embedded_subset = {
        key: value for key, value in embedded.items() if key not in _POST_ACCESS_FIELDS
    }
    if sha256_json(embedded_subset) != recorded_pre_access_checksum:
        raise DurableLedgerError(
            "the terminal's embedded pre-access provenance subset does not match the "
            "persisted pre-access ledger subset checksum (non-circular binding broken)."
        )

    expanded_provenance = _expand_embedded_provenance(embedded)
    pre_access_artifacts = {rec["name"]: rec["sha256"] for rec in pre_access_dict["artifacts"]}
    for name, value in expanded_provenance.items():
        if name in pre_access_artifacts and pre_access_artifacts[name] != value:
            raise DurableLedgerError(
                f"shared provenance field {name!r} disagrees between the pre-access "
                f"ledger ({pre_access_artifacts[name]!r}) and the terminal embedded "
                f"provenance ({value!r})."
            )

    # --- Step 3: build phase2b_registered_summary.json by copy+normalise ONLY.
    _assert_no_raw_outcomes(registered_summary)  # coarse backstop (spec §2.1)
    summary_bytes = _canonical_bytes(registered_summary)
    summary_sha = hashlib.sha256(summary_bytes).hexdigest()
    summary_path = run_dir_resolved / REGISTERED_SUMMARY_FILENAME

    # --- Step 4: build phase2b_final_ledger.json = pre-access snapshot + expanded
    # provenance entries + write-once file-SHA entries. It NEVER records the marker
    # or itself (deliberate non-self-reference, spec §3.1).
    final_ledger = RunLedger.read(pre_access_resolved)
    terminal_sha = _file_sha(terminal_resolved)
    seed_sha = _file_sha(seed_resolved)

    # The seed-variability file the pre-access ledger digested must be byte-stable.
    if "development_seed_variability" in pre_access_artifacts and (
        pre_access_artifacts["development_seed_variability"] != seed_sha
    ):
        raise DurableLedgerError(
            "the seed-variability file SHA disagrees with the digest recorded in the "
            "pre-access ledger (the durable report was modified after binding)."
        )

    try:
        for name, value in expanded_provenance.items():
            if name not in pre_access_artifacts:
                final_ledger.record_artifact(name, value)
        final_ledger.record_artifact(terminal_resolved.name, terminal_sha)
        final_ledger.record_artifact(REGISTERED_SUMMARY_FILENAME, summary_sha)
        final_ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_FILENAME, seed_sha)
    except DuplicateArtifactError as exc:
        raise DurableLedgerError(
            f"write-once violation assembling the final ledger: {exc}"
        ) from exc
    final_ledger_bytes = _canonical_bytes(final_ledger.to_dict())
    final_ledger_sha = hashlib.sha256(final_ledger_bytes).hexdigest()
    final_ledger_path = run_dir_resolved / FINAL_LEDGER_FILENAME

    # Install summary + final ledger (each atomic + idempotent).
    install_or_verify_exact(summary_path, summary_bytes.decode("utf-8"))
    install_or_verify_exact(final_ledger_path, final_ledger_bytes.decode("utf-8"))

    # --- Step 5: re-read both and compare to the intended canonical bytes + SHA.
    if summary_path.read_bytes() != summary_bytes or _file_sha(summary_path) != summary_sha:
        raise DurableLedgerError(
            "published registered summary failed post-install re-verification."
        )
    if (
        final_ledger_path.read_bytes() != final_ledger_bytes
        or _file_sha(final_ledger_path) != final_ledger_sha
    ):
        raise DurableLedgerError("published final ledger failed post-install re-verification.")

    # --- Step 6: install phase2b_durable_commit.json LAST, binding every file SHA
    # with a self-excluding commit_checksum (spec §3.1). The marker binds the final
    # ledger EXTERNALLY (the final ledger does not record the marker).
    seed_self_checksum = _read_seed_report_checksum(seed_resolved)
    pre_access_sha = _file_sha(pre_access_resolved)
    marker_core = {
        "schema": DURABLE_COMMIT_SCHEMA,
        "protocol": terminal_body["protocol"],
        "run_id": run_id,
        "terminal_state": terminal_state.value,
        "terminal": {"filename": terminal_resolved.name, "sha256": terminal_sha},
        "registered_summary": {
            "filename": REGISTERED_SUMMARY_FILENAME,
            "sha256": summary_sha,
            "self_checksum": registered_summary_checksum,
        },
        "final_ledger": {"filename": FINAL_LEDGER_FILENAME, "sha256": final_ledger_sha},
        "pre_access_ledger": {"filename": PRE_ACCESS_LEDGER_FILENAME, "sha256": pre_access_sha},
        "seed_variability": {
            "filename": DEVELOPMENT_SEED_VARIABILITY_FILENAME,
            "sha256": seed_sha,
            "self_checksum": seed_self_checksum,
        },
    }
    commit_checksum = sha256_json(marker_core)
    marker = {**marker_core, COMMIT_CHECKSUM_FIELD: commit_checksum}
    marker_bytes = _canonical_bytes(marker)
    marker_path = run_dir_resolved / DURABLE_COMMIT_FILENAME
    install_or_verify_exact(marker_path, marker_bytes.decode("utf-8"))

    # --- Step 7: re-read the marker and re-verify self-checksum, every recorded file
    # SHA, and run id / state.
    marker_raw = marker_path.read_bytes()
    try:
        reloaded = json.loads(marker_raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - just installed
        raise DurableLedgerError(f"commit marker re-read is not valid JSON: {exc}") from exc
    if marker_raw != _canonical_bytes(reloaded):
        raise DurableLedgerError("commit marker re-read is not canonical JSON.")
    reloaded_core = {k: v for k, v in reloaded.items() if k != COMMIT_CHECKSUM_FIELD}
    if sha256_json(reloaded_core) != reloaded.get(COMMIT_CHECKSUM_FIELD):
        raise DurableLedgerError("commit marker self-checksum failed re-verification.")
    if reloaded.get("run_id") != run_id or reloaded.get("terminal_state") != terminal_state.value:
        raise DurableLedgerError("commit marker run_id / terminal_state failed re-verification.")
    file_sha_checks = (
        (terminal_resolved, reloaded["terminal"]["sha256"]),
        (summary_path, reloaded["registered_summary"]["sha256"]),
        (final_ledger_path, reloaded["final_ledger"]["sha256"]),
        (pre_access_resolved, reloaded["pre_access_ledger"]["sha256"]),
        (seed_resolved, reloaded["seed_variability"]["sha256"]),
    )
    for path, expected_sha in file_sha_checks:
        if _file_sha(path) != expected_sha:
            raise DurableLedgerError(
                f"commit marker file-SHA for {str(path)!r} failed re-verification."
            )

    return DurableFinalizeResult(
        run_dir=run_dir_resolved,
        terminal_state=terminal_state.value,
        terminal_path=terminal_resolved,
        registered_summary_path=summary_path,
        final_ledger_path=final_ledger_path,
        commit_marker_path=marker_path,
        commit_checksum=commit_checksum,
    )


# ---------------------------------------------------------------------------
# Idempotent recovery (spec §3.2)
# ---------------------------------------------------------------------------


def _regular_file_sha(path: Path, *, label: str) -> str:
    """SHA-256 of a REGULAR (non-symlink) file's bytes, else fail closed.

    Raises
    ------
    DurableLedgerError
        If ``path`` is a symlink, absent, unreadable, or not a regular file.
    """
    if path.is_symlink():
        raise DurableLedgerError(f"{label} {str(path)!r} is a symlink; refused.")
    try:
        st = os.stat(path)
    except OSError as exc:
        raise DurableLedgerError(f"{label} {str(path)!r} is absent or unreadable: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise DurableLedgerError(f"{label} {str(path)!r} is not a regular file.")
    return _file_sha(path)


def _verify_seed_against_pre_access(seed_path: Path, pre_access_path: Path) -> None:
    """Verify the seed report's on-disk bytes/SHA against the pre-access ledger.

    Unconditional in recovery (spec §3.2): if the pre-access ledger recorded a
    ``development_seed_variability`` digest, the on-disk regular-file SHA MUST match
    it; a missing or byte-divergent seed report fails closed (no commit marker),
    regardless of whether the marker exists. Also validates the report's
    self-excluding self-checksum (M1).

    Raises
    ------
    DurableLedgerError
        If the seed file is absent / not a regular file, its SHA disagrees with the
        pre-access ledger digest, or its self-checksum does not bind its payload.
    """
    seed_sha = _regular_file_sha(seed_path, label="seed-variability report")
    try:
        pre_access_ledger = RunLedger.read(pre_access_path)
    except LedgerError as exc:
        raise DurableLedgerError(
            f"pre-access ledger {str(pre_access_path)!r} is not a valid ledger: {exc}"
        ) from exc
    recorded = {rec["name"]: rec["sha256"] for rec in pre_access_ledger.to_dict()["artifacts"]}
    claimed = recorded.get("development_seed_variability")
    if claimed is not None and claimed != seed_sha:
        raise DurableLedgerError(
            "the seed-variability file SHA disagrees with the digest recorded in the "
            "pre-access ledger (the durable report was modified after binding); "
            "no commit marker is produced."
        )
    # M1: the seed report's own self-excluding self-checksum must bind its payload.
    _read_seed_report_checksum(seed_path)


def _verify_only_recover(
    *,
    run_dir_resolved: Path,
    terminal_path: Path,
    terminal_state: TerminalState,
    pre_access_path: Path,
    seed_path: Path,
    marker_path: Path,
) -> DurableFinalizeResult:
    """Verify an already-published durable set without rewriting anything (spec §3.2).

    Re-verifies the marker's canonical form + self-checksum, the run_id / state
    against the sole on-disk terminal, and every recorded file SHA against the
    on-disk regular files. NEVER installs or rewrites; any mismatch fails closed.

    Handles both marker shapes: a summary-bearing (``COMPLETE`` / ``INVALID``)
    marker binds the published registered summary (checked here) and the result
    carries its path; an ``ABORTED_AFTER_SEAL`` marker has NO registered-summary
    field and no summary file (skipped here) and the result's
    ``registered_summary_path`` is ``None``.
    """
    summary_bearing = terminal_state in _SUMMARY_BEARING_STATES
    summary_path = run_dir_resolved / REGISTERED_SUMMARY_FILENAME
    final_ledger_path = run_dir_resolved / FINAL_LEDGER_FILENAME

    marker_raw = marker_path.read_bytes()
    try:
        marker = json.loads(marker_raw)
    except json.JSONDecodeError as exc:
        raise DurableLedgerError(
            f"commit marker {str(marker_path)!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise DurableLedgerError(f"commit marker {str(marker_path)!r} is not a JSON object.")
    if marker_raw != _canonical_bytes(marker):
        raise DurableLedgerError(f"commit marker {str(marker_path)!r} is not canonical JSON.")
    if COMMIT_CHECKSUM_FIELD not in marker:
        raise DurableLedgerError(
            f"commit marker {str(marker_path)!r} lacks a {COMMIT_CHECKSUM_FIELD!r} field."
        )
    core = {k: v for k, v in marker.items() if k != COMMIT_CHECKSUM_FIELD}
    if sha256_json(core) != marker[COMMIT_CHECKSUM_FIELD]:
        raise DurableLedgerError("commit marker self-checksum failed verification.")

    # run_id / state must agree with the sole on-disk terminal.
    terminal_raw = terminal_path.read_bytes()
    try:
        terminal_body = json.loads(terminal_raw)
    except json.JSONDecodeError as exc:
        raise DurableLedgerError(
            f"terminal {str(terminal_path)!r} is not valid JSON: {exc}"
        ) from exc
    run_id = terminal_body.get("run_id") if isinstance(terminal_body, dict) else None
    if not isinstance(run_id, str) or not run_id.strip():
        raise DurableLedgerError("terminal carries an empty run_id (un-attributable).")
    if marker.get("terminal_state") != terminal_state.value:
        raise DurableLedgerError(
            f"commit marker terminal_state {marker.get('terminal_state')!r} disagrees with "
            f"the on-disk terminal state {terminal_state.value!r}."
        )
    if marker.get("run_id") != run_id:
        raise DurableLedgerError(
            f"commit marker run_id {marker.get('run_id')!r} disagrees with the terminal "
            f"run_id {run_id!r}."
        )

    # Every recorded file SHA must match the on-disk regular file (never rewrite).
    # The registered-summary leg applies ONLY to the summary-bearing marker shape;
    # the abort marker carries no such field and no summary file.
    file_sha_checks = [(terminal_path, marker.get("terminal"), "terminal")]
    if summary_bearing:
        file_sha_checks.append(
            (summary_path, marker.get("registered_summary"), "registered summary")
        )
    file_sha_checks.extend(
        [
            (final_ledger_path, marker.get("final_ledger"), "final ledger"),
            (pre_access_path, marker.get("pre_access_ledger"), "pre-access ledger"),
            (seed_path, marker.get("seed_variability"), "seed-variability report"),
        ]
    )
    for path, record, label in file_sha_checks:
        expected_sha = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(expected_sha, str) or not expected_sha:
            raise DurableLedgerError(f"commit marker lacks a {label} sha256 record (fail closed).")
        if _regular_file_sha(path, label=label) != expected_sha:
            raise DurableLedgerError(
                f"commit marker {label} file-SHA failed verification (durable set tampered)."
            )

    return DurableFinalizeResult(
        run_dir=run_dir_resolved,
        terminal_state=terminal_state.value,
        terminal_path=terminal_path,
        registered_summary_path=summary_path if summary_bearing else None,
        final_ledger_path=final_ledger_path,
        commit_marker_path=marker_path,
        commit_checksum=marker[COMMIT_CHECKSUM_FIELD],
    )


def _synthesize_aborted_after_seal_terminal(
    run_dir_resolved: Path,
    *,
    audit_path: Path,
) -> None:
    """Synthesize the missing ``ABORTED_AFTER_SEAL`` terminal for the audit=1/terminal=0 state.

    A hard process death AFTER the durable seal claim burns
    the mode-specific write-once audit but may land before any terminal is written, leaving a
    consumed seal with no durable terminal record. This routes the on-disk recovery
    inputs (the persisted pre-access ledger for the two provenance identity anchors +
    run id, and the self-checksum-verified seed-variability report for the protocol —
    :class:`~alive.provenance.RunLedger` carries no protocol) into the SANCTIONED
    :meth:`~alive.compose.terminal.Phase2bTerminal.recover_aborted_after_seal`, which
    writes the sole ``ABORTED_AFTER_SEAL`` terminal recording the already-consumed seal.
    It opens NO seal, constructs NO outcome store and creates NO exclusive lock; the
    seal count + durable audit reference are derived from the burned audit.

    The two pre-access anchors are bound to EXACTLY the values
    :func:`_finalize_aborted_terminal` cross-checks: ``pre_access_ledger_sha256`` is the
    on-disk pre-access ledger file SHA and ``pre_access_provenance_checksum`` is the
    persisted pre-access provenance subset checksum (``artifact_sha`` of
    :data:`~alive.compose.provenance2.PRE_ACCESS_PROVENANCE_ARTIFACT`). Every read is
    wrapped so a missing / invalid pre-access ledger, a missing provenance subset
    checksum, a tampered / protocol-less seed report, or a burned audit with no records
    fails CLOSED with :class:`DurableLedgerError` — no terminal is fabricated when the
    seal was not consumed.

    Raises
    ------
    DurableLedgerError
        On any missing / invalid recovery input, or if the burned audit has no records.
    """
    pre_access_path = run_dir_resolved / PRE_ACCESS_LEDGER_FILENAME
    try:
        pre_access = RunLedger.read(pre_access_path)
    except LedgerError as exc:
        raise DurableLedgerError(
            f"recover: pre-access ledger {str(pre_access_path)!r} is absent or invalid; "
            "cannot synthesize an ABORTED_AFTER_SEAL terminal for the audit-only crash "
            "state (fail closed)."
        ) from exc
    try:
        pre_access_provenance_checksum = pre_access.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)
    except LedgerError as exc:
        raise DurableLedgerError(
            "recover: pre-access ledger is missing the pre-access provenance subset "
            f"checksum {PRE_ACCESS_PROVENANCE_ARTIFACT!r}; cannot synthesize (fail closed)."
        ) from exc
    run_id = pre_access.to_dict().get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise DurableLedgerError(
            "recover: pre-access ledger carries an empty run_id; cannot synthesize an "
            "attributable ABORTED_AFTER_SEAL terminal (fail closed)."
        )

    # The protocol-global scientific audit may live outside run_dir. Bind it to
    # this exact run before synthesizing a terminal so an operator cannot point
    # recovery at another protocol/run's burned claim.
    if audit_path.is_symlink():
        raise DurableLedgerError(
            f"recover: seal audit {str(audit_path)!r} is a symlink; refused (fail closed)."
        )
    try:
        audit_stat = audit_path.stat()
        audit_lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DurableLedgerError(
            f"recover: seal audit {str(audit_path)!r} is absent or unreadable: {exc}"
        ) from exc
    if not stat.S_ISREG(audit_stat.st_mode):
        raise DurableLedgerError(
            f"recover: seal audit {str(audit_path)!r} is not a regular file (fail closed)."
        )
    first_record: dict[str, object] | None = None
    for line in audit_lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DurableLedgerError(
                f"recover: seal audit {str(audit_path)!r} contains invalid JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise DurableLedgerError(
                f"recover: seal audit {str(audit_path)!r} contains a non-object record."
            )
        first_record = parsed
        break
    if first_record is None:
        raise DurableLedgerError(
            f"recover: seal audit {str(audit_path)!r} has no durable records; "
            "the seal was not consumed (fail closed)."
        )
    if first_record.get("run_id") != run_id:
        raise DurableLedgerError(
            f"recover: seal audit run_id {first_record.get('run_id')!r} != "
            f"pre-access ledger run_id {run_id!r} (fail closed)."
        )

    # Protocol comes from the SELF-CHECKSUM-VERIFIED seed report (RunLedger has no
    # protocol). _read_seed_report_checksum fails closed on a missing / unreadable /
    # bad-self-checksum report before we read the bound protocol value.
    seed_path = run_dir_resolved / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    _read_seed_report_checksum(seed_path)
    try:
        seed_doc = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - just validated above
        raise DurableLedgerError(
            f"recover: seed-variability report {str(seed_path)!r} is not readable JSON: {exc}"
        ) from exc
    protocol = seed_doc.get("protocol") if isinstance(seed_doc, dict) else None
    if not isinstance(protocol, str) or not protocol.strip():
        raise DurableLedgerError(
            f"recover: seed-variability report {str(seed_path)!r} has no usable 'protocol' "
            "to attribute the synthesized terminal (fail closed)."
        )

    try:
        Phase2bTerminal.recover_aborted_after_seal(
            run_dir_resolved,
            ledger=pre_access,
            audit_path=audit_path,
            protocol=protocol,
            run_id=run_id,
            pre_access_ledger_sha256=sha256_file(pre_access_path),
            pre_access_provenance_checksum=pre_access_provenance_checksum,
            exception=RuntimeError(
                "recovered: process death after seal claim, before terminal write"
            ),
            stage="recover_audit_only",
        )
    except TerminalError as exc:
        raise DurableLedgerError(
            "recover: cannot synthesize an ABORTED_AFTER_SEAL terminal for the audit-only "
            f"crash state: {exc}"
        ) from exc


def recover_phase2b_durable_outputs(
    *,
    run_dir: str | Path,
    audit_path: str | Path | None = None,
) -> DurableFinalizeResult:
    """Idempotently recover / complete the durable publish for a run (spec §3.2).

    Independently scans ``run_dir`` for the single sealed terminal and branches on
    the presence of the commit marker:

    - 0 or ≥2 terminals: fail closed.
    - 1 terminal + NO marker: re-run the forward publish idempotently — the full
      §3.1 path for a summary-bearing (``COMPLETE`` / ``INVALID``) terminal, or the
      reduced §3.3 abort publish for an ``ABORTED_AFTER_SEAL`` terminal. Every
      derived byte is deterministic canonical JSON + file SHAs, so a byte-identical
      re-derivation reproduces the SAME marker. This is DERIVED-FILE recovery: NO
      seal is reopened, nothing is re-scored, no terminal re-transitioned.
    - 1 terminal + a marker: VERIFY ONLY — re-verify the marker's self-checksum,
      run_id / state, and every recorded file SHA (the summary leg only for a
      summary-bearing marker); NEVER rewrite.

    In every branch the seed-variability artifact's on-disk regular-file bytes/SHA
    are verified against the pre-access ledger record (spec §3.2): a claimed seed
    digest whose file is absent or whose bytes differ prevents a commit marker.

    Parameters
    ----------
    run_dir : str or Path
        The run directory holding the terminal, pre-access ledger, seed report and
        (when already published) the derived files + marker.
    audit_path : str or Path or None
        The burned seal audit used only for ``terminal=0`` synthesis. ``None``
        preserves the fixture/legacy ``<run_dir>/audit.jsonl`` default;
        scientific recovery must pass its declared protocol-global audit path.

    Returns
    -------
    DurableFinalizeResult
        The verified (re-)published or verify-only result.

    Raises
    ------
    DurableLedgerError
        On any terminal-count, path-safety, marker, checksum, file-SHA or seed
        cross-check failure.
    """
    run_dir_resolved = _resolve_run_dir(run_dir)
    if audit_path is None:
        audit_path_resolved = run_dir_resolved / SEAL_AUDIT_FILENAME
    else:
        audit_path_resolved = Path(os.path.abspath(str(audit_path)))

    # --- Task 7 (C0 #5) terminal-count branch: the audit=1 / terminal=0 post-crash
    # state has NO terminal yet — a process death after claim_sealed_access burned the
    # durable audit but landed before any terminal was written. Synthesize the sole
    # missing ABORTED_AFTER_SEAL terminal via the sanctioned recovery entry (opens NO
    # seal), then fall through to the ordinary single-terminal recovery below (which now
    # finds exactly 1 and takes the reduced §3.3 abort publish). 0 records / no
    # pre-access inputs fail closed inside the synthesizer; ≥2 terminals fail closed here.
    terminals = _scan_terminals(run_dir_resolved)
    if len(terminals) >= 2:
        raise DurableLedgerError(
            f"expected 0 or 1 terminal artifact in {str(run_dir_resolved)!r}; found "
            f"{sorted(terminals)!r} (fail closed)."
        )
    if not terminals:
        _synthesize_aborted_after_seal_terminal(
            run_dir_resolved,
            audit_path=audit_path_resolved,
        )

    terminal_name = _scan_single_terminal(run_dir_resolved)
    terminal_state = _TERMINAL_FILENAME_STATE[terminal_name]
    terminal_path = run_dir_resolved / terminal_name
    pre_access_path = run_dir_resolved / PRE_ACCESS_LEDGER_FILENAME
    seed_path = run_dir_resolved / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    marker_path = run_dir_resolved / DURABLE_COMMIT_FILENAME

    # Unconditional seed cross-check (spec §3.2): the seed report the pre-access
    # ledger digested must be a present, byte-stable regular file, marker or not.
    _verify_seed_against_pre_access(seed_path, pre_access_path)

    # Marker presence (a symlink or non-regular marker fails closed).
    if marker_path.is_symlink():
        raise DurableLedgerError(
            f"commit marker {str(marker_path)!r} is a symlink; refused (fail closed)."
        )
    try:
        marker_st = os.stat(marker_path)
    except FileNotFoundError:
        marker_present = False
    except OSError as exc:
        raise DurableLedgerError(
            f"commit marker {str(marker_path)!r} could not be stat-ed: {exc}"
        ) from exc
    else:
        if not stat.S_ISREG(marker_st.st_mode):
            raise DurableLedgerError(
                f"commit marker {str(marker_path)!r} exists but is not a regular file."
            )
        marker_present = True

    if not marker_present:
        # Derived-file recovery: re-run the forward publish idempotently — the full
        # §3.1 path for a summary-bearing terminal, the reduced §3.3 abort publish for
        # an ABORTED_AFTER_SEAL terminal. install_or_verify_exact makes byte-identical
        # re-derivation a no-op and any divergence fail closed; the full terminal
        # verification (incl. the shared payload-checksum canonicalizer) always runs.
        return finalize_phase2b_durable_outputs(
            run_dir=run_dir_resolved,
            terminal_path=terminal_path,
            pre_access_ledger_path=pre_access_path,
            seed_variability_path=seed_path,
        )

    return _verify_only_recover(
        run_dir_resolved=run_dir_resolved,
        terminal_path=terminal_path,
        terminal_state=terminal_state,
        pre_access_path=pre_access_path,
        seed_path=seed_path,
        marker_path=marker_path,
    )
