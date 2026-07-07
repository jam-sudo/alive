"""D1 durable-publish finalizer for COMPOSE Phase-2b terminal outputs.

The single sealed terminal artifact is the authoritative recovery source (spec
§1). Individual files are installed atomically and write-once, but *set*
completeness is decided by ONE marker installed LAST —
``phase2b_durable_commit.json``. Absent that marker the durable export is
INCOMPLETE and only a recovery-only path may complete it; the seal is never
reopened (spec §1, §3.1).

:func:`finalize_phase2b_durable_outputs` reads the already-written durable inputs
— the sealed terminal, the persisted pre-access ledger snapshot, and the D2
seed-variability report — and publishes three DERIVED files: the outcome-free
``phase2b_registered_summary.json`` (a byte-faithful copy+normalise of the
terminal's ``registered_summary``), ``phase2b_final_ledger.json`` (the pre-access
ledger snapshot + the terminal's embedded provenance expanded into individual
canonical entries + write-once file-SHA entries), and finally the single
``phase2b_durable_commit.json`` marker binding every file SHA with a
self-excluding ``commit_checksum``.

This module opens NO seal and constructs NO outcome store. It only reads durable
files and publishes derived files (forward publish + verification). The
idempotent recovery variant (``install_or_verify_exact``) is Task 6; this module
uses plain write-once installs, so a re-run over already-published derived files
fails closed rather than overwriting.

The whole-body ``terminal_payload_checksum`` is verified through the ONE shared
:func:`~alive.compose.terminal.canonicalize_terminal_checksum_input`, never by
``sha256_json`` over the raw decoded body — a real terminal carries finite floats
whose persisted JSON number differs from the ``float.hex()`` string the writer
hashed (spec §2, CLAUDE.md §11).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

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
    TerminalState,
    _assert_no_raw_outcomes,
    canonicalize_terminal_checksum_input,
)
from alive.io import atomic_write_once
from alive.provenance import (
    DuplicateArtifactError,
    LedgerError,
    RunLedger,
    sha256_json,
)

#: Published derived-file names (all direct children of the run dir).
REGISTERED_SUMMARY_FILENAME = "phase2b_registered_summary.json"
FINAL_LEDGER_FILENAME = "phase2b_final_ledger.json"
DURABLE_COMMIT_FILENAME = "phase2b_durable_commit.json"

#: Versioned schema string carried by the durable commit marker.
DURABLE_COMMIT_SCHEMA = "compose_phase2b_durable_commit_v1"

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
#: therefore publishable by this forward-publish finalizer (spec §2.1). An
#: ``ABORTED_AFTER_SEAL`` terminal carries no registered summary; its durable
#: finalize is a separate concern and is refused here (fail closed).
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
        The verified terminal state value (``"COMPLETE"`` / ``"INVALID"``).
    terminal_path : Path
        The resolved single sealed terminal artifact (the recovery source).
    registered_summary_path : Path
        The published outcome-free registered summary.
    final_ledger_path : Path
        The published final ledger (pre-access snapshot + expanded provenance +
        write-once file-SHA entries).
    commit_marker_path : Path
        The single durable commit marker installed LAST.
    commit_checksum : str
        The marker's self-excluding ``commit_checksum``.
    """

    run_dir: Path
    terminal_state: str
    terminal_path: Path
    registered_summary_path: Path
    final_ledger_path: Path
    commit_marker_path: Path
    commit_checksum: str


def _canonical_bytes(obj: object) -> bytes:
    """Canonical JSON bytes (``sort_keys`` + compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _file_sha(path: Path) -> str:
    """SHA-256 hex of a file's raw bytes (the durable file-SHA convention)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _install(path: Path, text: str) -> None:
    """Atomic, write-once install; a pre-existing destination fails closed.

    Raises
    ------
    DurableLedgerError
        If ``path`` already exists (write-once; the idempotent recovery variant
        is Task 6) or the atomic install otherwise fails.
    """
    try:
        atomic_write_once(path, text)
    except FileExistsError as exc:
        raise DurableLedgerError(
            f"durable output {str(path)!r} already exists; forward publish is "
            "write-once and never overwrites (recovery is a separate path)."
        ) from exc
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise DurableLedgerError(f"failed to install durable output {str(path)!r}: {exc}") from exc


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


def _read_seed_report_checksum(path: Path) -> str:
    """Extract the seed-variability report's self-excluding ``report_checksum``."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} is not readable JSON: {exc}"
        ) from exc
    if not isinstance(doc, dict) or "report_checksum" not in doc:
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} lacks a 'report_checksum' field."
        )
    checksum = doc["report_checksum"]
    if not isinstance(checksum, str) or not checksum.strip():
        raise DurableLedgerError(
            f"seed-variability report {str(path)!r} carries an empty report_checksum."
        )
    return checksum


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
    marker installed LAST), following the exact publish order of spec §3.1. Opens
    NO seal and constructs NO outcome store.

    Parameters
    ----------
    run_dir : str or Path
        The run directory; every input and derived file must be a direct child.
    terminal_path : str or Path
        The single sealed terminal artifact (COMPLETE / INVALID).
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
    run_dir_path = Path(run_dir)
    if run_dir_path.is_symlink():
        raise DurableLedgerError(f"run_dir {str(run_dir_path)!r} is a symlink; refused.")
    try:
        run_st = os.stat(run_dir_path)
    except OSError as exc:
        raise DurableLedgerError(f"run_dir {str(run_dir_path)!r} is not accessible: {exc}") from exc
    if not stat.S_ISDIR(run_st.st_mode):
        raise DurableLedgerError(f"run_dir {str(run_dir_path)!r} is not a directory.")
    run_dir_resolved = run_dir_path.resolve()

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
    if len(scanned) != 1:
        raise DurableLedgerError(
            f"expected EXACTLY ONE terminal artifact in {str(run_dir_resolved)!r}; "
            f"found {scanned!r} (fail closed)."
        )
    if scanned[0] != terminal_resolved.name:
        raise DurableLedgerError(
            f"caller terminal {terminal_resolved.name!r} disagrees with the sole "
            f"terminal on disk {scanned[0]!r}."
        )
    terminal_state = _TERMINAL_FILENAME_STATE[terminal_resolved.name]
    if terminal_state not in _SUMMARY_BEARING_STATES:
        raise DurableLedgerError(
            f"terminal state {terminal_state.value!r} carries no registered summary; "
            "the forward-publish finalizer handles only COMPLETE / INVALID."
        )

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

    # Install summary + final ledger (each atomic, write-once).
    _install(summary_path, summary_bytes.decode("utf-8"))
    _install(final_ledger_path, final_ledger_bytes.decode("utf-8"))

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
    _install(marker_path, marker_bytes.decode("utf-8"))

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
