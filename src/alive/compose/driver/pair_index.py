"""Pair-index manifest v1 pre-seal validation (COMPOSE production driver).

The ``pair_index_manifest`` a :class:`~alive.compose.driver.run_spec.ResolvedRunSpec`
points at binds every canonical pair to the source rows it will draw from once
the seal opens. At pre-seal time — before ``phase2b`` confirmation — the driver
may verify only the manifest's own DECLARED bytes: its v1 schema shape, its
``self_checksum``, and its binding to the ``approved_sealed_input_attestation``
(spec §2.2's attestation paragraph, ~line 226; spec §2.3). It may NOT open the
sealed source to check those declared bytes against reality.

Outcome-free row-index overlap and split-union checks run when ``phase2b``
constructs its lazy store after confirmation. The outcome-bearing semantic
check — whether each indexed row's obs perturbation label canonicalizes to its
declared pair — is C0's
:func:`alive.compose.outcome_store.validate_pair_index_against_source_obs`,
called ONLY from ``phase2b`` step 5 after the durable audit claim (spec §2.3).
This module never imports that function, never opens a file, and never
constructs a store: it is pure validation over two already-parsed
:class:`~collections.abc.Mapping` objects.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md
§2.2 (``approved_sealed_input_attestation`` paragraph) and §2.3.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from alive.compose.driver.run_spec import RunSpecError
from alive.compose.driver.seal_boundary import scientific_protocol_seal_audit_path
from alive.compose.roles import ROLE_NAMES
from alive.provenance import sha256_json

__all__ = [
    "PAIR_INDEX_MANIFEST_SCHEMA",
    "PAIR_INDEX_MANIFEST_KEYS",
    "PAIR_ENTRY_KEYS",
    "ATTESTATION_SCHEMA",
    "ATTESTATION_KEYS",
    "validate_pair_index_manifest_preseal",
    "validate_scientific_sealed_declaration",
]

#: Exact ``schema`` discriminator every v1 pair-index manifest must carry.
PAIR_INDEX_MANIFEST_SCHEMA = "compose_pair_index_manifest_v1"

#: Exact top-level key roster of a v1 pair-index manifest (spec §2.3):
#: source file SHA, obs row-identity SHA, perturbation column, control/combo
#: token rules, the per-canonical-pair roster, and the self-checksum.
PAIR_INDEX_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "source_file_sha256",
        "obs_row_identity_sha256",
        "perturbation_column",
        "control_token",
        "combo_sep",
        "pairs",
        "self_checksum",
    }
)

#: Exact key roster of one ``pairs[i]`` entry: the canonical gene pair, its
#: split role, its row indices, and a per-pair row-ID digest.
PAIR_ENTRY_KEYS: frozenset[str] = frozenset(
    {"gene_a", "gene_b", "role", "row_indices", "row_id_sha256"}
)

#: Exact ``schema`` discriminator every v1 ``approved_sealed_input_attestation``
#: must carry (spec §2.2: canonical source path, expected source file SHA,
#: snapshot ID, source row-identity SHA, pair-index file SHA, self-checksum).
ATTESTATION_SCHEMA = "compose_approved_sealed_input_attestation_v1"

#: Exact top-level key roster of a v1 ``approved_sealed_input_attestation``.
ATTESTATION_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "canonical_source_path",
        "expected_source_file_sha256",
        "snapshot_id",
        "source_row_identity_sha256",
        "pair_index_file_sha256",
        "self_checksum",
    }
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.match(value))


def _require_hex64(obj: Mapping[str, Any], key: str, *, where: str) -> str:
    value = obj.get(key)
    if not _is_hex64(value):
        raise RunSpecError(f"{where}: {key!r} must be 64 lowercase hex chars, got {value!r}")
    return value


def _require_nonempty_str(obj: Mapping[str, Any], key: str, *, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or value == "":
        raise RunSpecError(f"{where}: {key!r} must be a non-empty string, got {value!r}")
    return value


def _validate_pair_entry(entry: Any, *, index: int) -> tuple[str, str]:
    """Validate one ``pairs[i]`` entry's shape; return its canonical pair key."""
    where = f"pair_index_manifest.pairs[{index}]"
    if not isinstance(entry, dict):
        raise RunSpecError(f"{where}: must be an object")
    actual = set(entry)
    if actual != PAIR_ENTRY_KEYS:
        raise RunSpecError(
            f"{where}: key roster mismatch: "
            f"missing={sorted(PAIR_ENTRY_KEYS - actual)} "
            f"unexpected={sorted(actual - PAIR_ENTRY_KEYS)}"
        )

    gene_a = _require_nonempty_str(entry, "gene_a", where=where)
    gene_b = _require_nonempty_str(entry, "gene_b", where=where)
    if gene_a == gene_b:
        raise RunSpecError(f"{where}: gene_a == gene_b is not a valid pair: {gene_a!r}")
    if gene_a.encode("utf-8") >= gene_b.encode("utf-8"):
        raise RunSpecError(
            f"{where}: (gene_a, gene_b) must be in canonical UTF-8 byte order, "
            f"got ({gene_a!r}, {gene_b!r})"
        )

    role = entry.get("role")
    if role not in ROLE_NAMES:
        raise RunSpecError(f"{where}: 'role' must be one of {sorted(ROLE_NAMES)}, got {role!r}")

    row_indices = entry.get("row_indices")
    if not isinstance(row_indices, list) or not row_indices:
        raise RunSpecError(f"{where}: 'row_indices' must be a non-empty list")
    seen_rows: set[int] = set()
    for i, raw in enumerate(row_indices):
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise RunSpecError(f"{where}.row_indices[{i}]: must be an int, got {raw!r}")
        if raw < 0:
            raise RunSpecError(f"{where}.row_indices[{i}]: must be non-negative, got {raw}")
        if raw in seen_rows:
            raise RunSpecError(f"{where}.row_indices: duplicate row index {raw}")
        seen_rows.add(raw)

    _require_hex64(entry, "row_id_sha256", where=where)
    return (gene_a, gene_b)


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> tuple[str, str]:
    """Validate the manifest's v1 schema shape + self-checksum.

    Returns
    -------
    tuple of str
        ``(source_file_sha256, obs_row_identity_sha256)`` as declared.
    """
    if not isinstance(manifest, dict):
        raise RunSpecError("pair_index_manifest must be a mapping")

    actual_keys = set(manifest)
    if actual_keys != PAIR_INDEX_MANIFEST_KEYS:
        raise RunSpecError(
            "pair_index_manifest key roster mismatch: "
            f"missing={sorted(PAIR_INDEX_MANIFEST_KEYS - actual_keys)} "
            f"unexpected={sorted(actual_keys - PAIR_INDEX_MANIFEST_KEYS)}"
        )

    if manifest.get("schema") != PAIR_INDEX_MANIFEST_SCHEMA:
        raise RunSpecError(
            f"pair_index_manifest.schema must be {PAIR_INDEX_MANIFEST_SCHEMA!r}, "
            f"got {manifest.get('schema')!r}"
        )

    declared_self = manifest.get("self_checksum")
    if not _is_hex64(declared_self):
        raise RunSpecError("pair_index_manifest.self_checksum must be 64 lowercase hex chars")
    body = {k: v for k, v in manifest.items() if k != "self_checksum"}
    if declared_self != sha256_json(body):
        raise RunSpecError(
            "pair_index_manifest.self_checksum does not match payload (excluding self_checksum)"
        )

    source_file_sha256 = _require_hex64(manifest, "source_file_sha256", where="pair_index_manifest")
    obs_row_identity_sha256 = _require_hex64(
        manifest, "obs_row_identity_sha256", where="pair_index_manifest"
    )
    _require_nonempty_str(manifest, "perturbation_column", where="pair_index_manifest")
    _require_nonempty_str(manifest, "control_token", where="pair_index_manifest")
    _require_nonempty_str(manifest, "combo_sep", where="pair_index_manifest")

    pairs = manifest.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise RunSpecError("pair_index_manifest.pairs must be a non-empty list")
    seen_pairs: set[tuple[str, str]] = set()
    for i, entry in enumerate(pairs):
        pair = _validate_pair_entry(entry, index=i)
        if pair in seen_pairs:
            raise RunSpecError(f"pair_index_manifest.pairs: duplicate canonical pair {pair!r}")
        seen_pairs.add(pair)

    return source_file_sha256, obs_row_identity_sha256


def _validate_attestation_shape(attestation: Mapping[str, Any]) -> tuple[str, str, str]:
    """Validate the attestation's v1 schema shape + self-checksum.

    Returns
    -------
    tuple of str
        ``(expected_source_file_sha256, source_row_identity_sha256)`` as
        declared.
    """
    if not isinstance(attestation, dict):
        raise RunSpecError("approved_sealed_input_attestation must be a mapping")

    actual_keys = set(attestation)
    if actual_keys != ATTESTATION_KEYS:
        raise RunSpecError(
            "approved_sealed_input_attestation key roster mismatch: "
            f"missing={sorted(ATTESTATION_KEYS - actual_keys)} "
            f"unexpected={sorted(actual_keys - ATTESTATION_KEYS)}"
        )

    if attestation.get("schema") != ATTESTATION_SCHEMA:
        raise RunSpecError(
            f"approved_sealed_input_attestation.schema must be {ATTESTATION_SCHEMA!r}, "
            f"got {attestation.get('schema')!r}"
        )

    declared_self = attestation.get("self_checksum")
    if not _is_hex64(declared_self):
        raise RunSpecError(
            "approved_sealed_input_attestation.self_checksum must be 64 lowercase hex chars"
        )
    body = {k: v for k, v in attestation.items() if k != "self_checksum"}
    if declared_self != sha256_json(body):
        raise RunSpecError(
            "approved_sealed_input_attestation.self_checksum does not match payload "
            "(excluding self_checksum)"
        )

    _require_nonempty_str(
        attestation, "canonical_source_path", where="approved_sealed_input_attestation"
    )
    _require_nonempty_str(attestation, "snapshot_id", where="approved_sealed_input_attestation")
    expected_source_file_sha256 = _require_hex64(
        attestation, "expected_source_file_sha256", where="approved_sealed_input_attestation"
    )
    source_row_identity_sha256 = _require_hex64(
        attestation, "source_row_identity_sha256", where="approved_sealed_input_attestation"
    )
    pair_index_file_sha256 = _require_hex64(
        attestation, "pair_index_file_sha256", where="approved_sealed_input_attestation"
    )

    return expected_source_file_sha256, source_row_identity_sha256, pair_index_file_sha256


def validate_pair_index_manifest_preseal(
    manifest: Mapping[str, Any],
    *,
    attestation: Mapping[str, Any],
    pair_index_manifest_file_sha256: str,
) -> None:
    """Validate a pair-index manifest v1 at PRE-SEAL time — no source access.

    Verifies (spec §2.3 + §2.2's ``approved_sealed_input_attestation``
    paragraph):

    1. the manifest's exact v1 key roster (unknown/missing → raise) — source
       file SHA, obs row-identity SHA, perturbation column, control/combo
       token rules, the per-canonical-pair roster (row indices + row-ID
       digest + role for each), and ``self_checksum``;
    2. each ``pairs[i]`` entry's shape: a canonical (UTF-8 byte-ordered,
       non-self) gene pair, a role drawn from the registered split roles
       (:data:`alive.compose.roles.ROLE_NAMES`), a non-empty list of
       non-negative, non-duplicate row indices, and a 64-hex row-ID digest;
       no two entries may declare the same canonical pair;
    3. ``manifest.self_checksum == sha256_json(manifest excluding self_checksum)``;
    4. the attestation's own v1 shape and self-checksum;
    5. the binding: the attested ``pair_index_file_sha256`` equals the loader-
       verified SHA of the actual pair-index manifest file, and
       ``manifest.source_file_sha256 ==
       attestation.expected_source_file_sha256`` AND
       ``manifest.obs_row_identity_sha256 == attestation.source_row_identity_sha256``.

    This function opens NO file, parses NO AnnData, and constructs NO store —
    it is pure validation over two already-parsed mappings (pre-seal capability
    restriction; spec §2.2/§2.3). The semantic check that indexed rows'
    perturbation labels actually match their declared pair is performed later,
    ONLY by ``phase2b`` step 5 after its durable audit claim, via C0's
    :func:`alive.compose.outcome_store.validate_pair_index_against_source_obs`.
    Row overlap and split-union checks remain outcome-free store-construction
    guards and therefore run before that claim.

    Parameters
    ----------
    manifest : Mapping
        The parsed ``pair_index_manifest`` JSON object.
    attestation : Mapping
        The parsed ``approved_sealed_input_attestation`` JSON object.
    pair_index_manifest_file_sha256 : str
        SHA-256 of the actual pair-index manifest file, already stream-verified
        by :func:`load_resolved_run_spec`.

    Raises
    ------
    RunSpecError
        On ANY schema, self-checksum, or attestation-binding violation.
    """
    source_file_sha256, obs_row_identity_sha256 = _validate_manifest_shape(manifest)
    (
        expected_source_file_sha256,
        source_row_identity_sha256,
        attested_pair_index_file_sha256,
    ) = _validate_attestation_shape(attestation)

    if re.fullmatch(r"[0-9a-f]{64}", pair_index_manifest_file_sha256) is None:
        raise RunSpecError("pair_index_manifest_file_sha256 must be 64 lowercase hex chars")
    if attested_pair_index_file_sha256 != pair_index_manifest_file_sha256:
        raise RunSpecError(
            "approved_sealed_input_attestation.pair_index_file_sha256 "
            f"({attested_pair_index_file_sha256}) != actual pair-index manifest file digest "
            f"({pair_index_manifest_file_sha256})"
        )

    if source_file_sha256 != expected_source_file_sha256:
        raise RunSpecError(
            "pair_index_manifest.source_file_sha256 "
            f"({source_file_sha256}) != approved_sealed_input_attestation."
            f"expected_source_file_sha256 ({expected_source_file_sha256})"
        )
    if obs_row_identity_sha256 != source_row_identity_sha256:
        raise RunSpecError(
            "pair_index_manifest.obs_row_identity_sha256 "
            f"({obs_row_identity_sha256}) != approved_sealed_input_attestation."
            f"source_row_identity_sha256 ({source_row_identity_sha256})"
        )


def validate_scientific_sealed_declaration(
    *,
    sealed_input: Mapping[str, Any],
    attestation: Mapping[str, Any],
    pair_index_manifest: Mapping[str, Any],
    pair_index_manifest_file_sha256: str,
    protocol: str,
    approved_artifacts_root: str,
) -> None:
    """Prove the scientific sealed_input binds to the owner attestation (§2.2) — lexical only.

    Reuses :func:`validate_pair_index_manifest_preseal` for the attestation shape + the
    manifest↔attestation (pair-index file SHA, source-file SHA, row-identity) bindings, then
    adds the sealed_input-specific equalities. The source path is checked as a STRING only: no
    ``resolve``, ``stat``, hash, AnnData parse, or source open. Source node identity + byte
    integrity remain Phase-2b-after-confirmation work.
    """
    validate_pair_index_manifest_preseal(
        pair_index_manifest,
        attestation=attestation,
        pair_index_manifest_file_sha256=pair_index_manifest_file_sha256,
    )
    if sealed_input.get("source_path") != attestation.get("canonical_source_path"):
        raise RunSpecError(
            "scientific sealed_input.source_path != attestation.canonical_source_path"
        )
    if sealed_input.get("expected_file_sha256") != attestation.get("expected_source_file_sha256"):
        raise RunSpecError(
            "scientific sealed_input.expected_file_sha256 != "
            "attestation.expected_source_file_sha256"
        )
    if sealed_input.get("snapshot_id") != attestation.get("snapshot_id"):
        raise RunSpecError("scientific sealed_input.snapshot_id != attestation.snapshot_id")
    try:
        expected_audit = scientific_protocol_seal_audit_path(approved_artifacts_root, protocol)
    except ValueError as exc:
        raise RunSpecError(f"scientific protocol seal boundary is invalid: {exc}") from exc
    declared_audit = str(sealed_input.get("audit_path"))
    if declared_audit != str(expected_audit):
        raise RunSpecError(
            f"scientific sealed_input.audit_path ({declared_audit}) != "
            f"canonical protocol-global seal audit ({expected_audit})"
        )
