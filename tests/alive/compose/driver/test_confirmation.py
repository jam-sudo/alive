"""Tests for the seal-confirmation manifest v1 build/install/verify (spec §3.2 tail, §3.3 step 3).

Builds real manifests, installs them write-once via real files (no mocks), and
exercises :func:`verify_seal_confirmation_manifest` against a real token and
real ``reconstruct_inputs``. Covers the round trip, the run-id-only-token
landmine, a tampered stored manifest, a diverging reconstruct input, and a
roster that isn't exactly the registered ``config2`` constants.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from alive.compose.config2 import _EXPECTED_COMPARATOR_FAMILY, _EXPECTED_METHOD_ROSTER
from alive.compose.driver.confirmation import (
    SEAL_CONFIRMATION_MANIFEST_SCHEMA,
    ConfirmationError,
    build_seal_confirmation_manifest,
    install_seal_confirmation_manifest,
    verify_seal_confirmation_manifest,
)
from alive.provenance import sha256_json


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _preseal_checksums(salt: str = "") -> dict:
    return {
        "config_checksum": _hex(f"config{salt}"),
        "data_card_checksum": _hex(f"data_card{salt}"),
        "manifest_checksum": _hex(f"manifest{salt}"),
        "response_space_checksum": _hex(f"response_space{salt}"),
        "factor_checksum": _hex(f"factor{salt}"),
        "model_checksum": _hex(f"model{salt}"),
        "bundle_checksum": _hex(f"bundle{salt}"),
        "ledger_checksum": _hex(f"ledger{salt}"),
        "pair_index_checksum": _hex(f"pair_index{salt}"),
        "seed_report_checksum": _hex(f"seed_report{salt}"),
    }


def _build_inputs(salt: str = "") -> dict:
    return {
        "run_id": f"run-{salt or 'abc'}",
        "execution_id": _hex(f"execution{salt}"),
        "resolved_run_spec_file_sha256": _hex(f"spec_file{salt}"),
        "approved_git_sha": "a" * 40,
        "git_clean": True,
        "preseal_checksums": _preseal_checksums(salt),
    }


def _canonical_bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------- #
# build_seal_confirmation_manifest
# --------------------------------------------------------------------------- #


def test_build_returns_self_checksummed_v1_manifest():
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)

    assert manifest["schema"] == SEAL_CONFIRMATION_MANIFEST_SCHEMA
    assert manifest["run_id"] == inputs["run_id"]
    assert manifest["execution_id"] == inputs["execution_id"]
    assert manifest["resolved_run_spec_file_sha256"] == inputs["resolved_run_spec_file_sha256"]
    assert manifest["approved_git_sha"] == inputs["approved_git_sha"]
    assert manifest["git_clean"] is True
    assert manifest["preseal_checksums"] == inputs["preseal_checksums"]
    assert manifest["method_roster"] == list(_EXPECTED_METHOD_ROSTER)
    assert manifest["comparator_roster"] == list(_EXPECTED_COMPARATOR_FAMILY)

    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    assert manifest["confirmation_checksum"] == sha256_json(body)


def test_build_method_roster_matches_config2_exactly_and_order_fixed():
    manifest = build_seal_confirmation_manifest(**_build_inputs())
    assert manifest["method_roster"] == list(_EXPECTED_METHOD_ROSTER)
    assert len(manifest["method_roster"]) == 9
    assert manifest["comparator_roster"] == list(_EXPECTED_COMPARATOR_FAMILY)
    assert len(manifest["comparator_roster"]) == 5


@pytest.mark.parametrize(
    "override,error_fragment",
    [
        ({"run_id": ""}, "run_id"),
        ({"execution_id": ""}, "execution_id"),
        ({"resolved_run_spec_file_sha256": "not-hex"}, "resolved_run_spec_file_sha256"),
        ({"approved_git_sha": ""}, "approved_git_sha"),
        ({"git_clean": "yes"}, "git_clean"),
        ({"preseal_checksums": {}}, "preseal_checksums"),
        ({"preseal_checksums": {"config_checksum": "not-hex"}}, "preseal_checksums"),
    ],
)
def test_build_rejects_malformed_inputs(override, error_fragment):
    inputs = _build_inputs()
    inputs.update(override)
    with pytest.raises(ConfirmationError, match=error_fragment):
        build_seal_confirmation_manifest(**inputs)


# --------------------------------------------------------------------------- #
# round trip: build -> install -> verify
# --------------------------------------------------------------------------- #


def test_round_trip_build_install_verify_passes(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    assert path.exists()
    on_disk = json.loads(path.read_bytes())
    assert on_disk == manifest
    assert _canonical_bytes(on_disk) == path.read_bytes()

    # No raise == pass.
    verify_seal_confirmation_manifest(
        path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
    )


def test_install_is_write_once(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    with pytest.raises(ConfirmationError):
        install_seal_confirmation_manifest(path, manifest)


def test_install_rejects_a_manifest_with_broken_self_checksum(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    manifest["confirmation_checksum"] = "0" * 64  # break it before install
    path = tmp_path / "seal_confirmation_manifest.json"

    with pytest.raises(ConfirmationError):
        install_seal_confirmation_manifest(path, manifest)
    assert not path.exists()


# --------------------------------------------------------------------------- #
# verify: the run-id-only-token landmine
# --------------------------------------------------------------------------- #


def test_verify_rejects_a_run_id_only_token(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    with pytest.raises(ConfirmationError, match="confirmation_checksum"):
        verify_seal_confirmation_manifest(path, inputs["run_id"], reconstruct_inputs=inputs)


def test_verify_rejects_any_non_matching_token(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(path, "0" * 64, reconstruct_inputs=inputs)


# --------------------------------------------------------------------------- #
# verify: a tampered stored manifest (self-checksum broken)
# --------------------------------------------------------------------------- #


def test_verify_rejects_a_tampered_stored_manifest(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    real_token = manifest["confirmation_checksum"]

    # Tamper the stored bytes directly (bypassing the installer's own
    # self-check) so the self-checksum no longer matches the payload.
    tampered = dict(manifest)
    tampered["approved_git_sha"] = "b" * 40
    # confirmation_checksum intentionally NOT recomputed -> self-checksum broken.
    path = tmp_path / "seal_confirmation_manifest.json"
    path.write_bytes(_canonical_bytes(tampered))

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(path, real_token, reconstruct_inputs=inputs)


# --------------------------------------------------------------------------- #
# verify: a changed reconstruct input diverges from the stored manifest
# --------------------------------------------------------------------------- #


def test_verify_rejects_a_diverging_reconstruct_input(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    changed_inputs = dict(inputs)
    changed_checksums = dict(inputs["preseal_checksums"])
    changed_checksums["config_checksum"] = _hex("a-different-config-file")
    changed_inputs["preseal_checksums"] = changed_checksums

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=changed_inputs
        )


def test_verify_rejects_a_diverging_git_clean_reconstruct_input(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    changed_inputs = dict(inputs)
    changed_inputs["git_clean"] = False

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=changed_inputs
        )


def test_verify_rejects_reconstruct_inputs_missing_keys(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    incomplete_inputs = dict(inputs)
    del incomplete_inputs["git_clean"]

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=incomplete_inputs
        )


# --------------------------------------------------------------------------- #
# verify: a roster that isn't exactly the config2 constants
# --------------------------------------------------------------------------- #


def test_verify_rejects_a_method_roster_that_is_not_config2_constant(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    manifest["method_roster"] = list(_EXPECTED_METHOD_ROSTER)[:-1]  # drop one entry
    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    manifest["confirmation_checksum"] = sha256_json(body)  # self-consistent, but wrong roster

    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


def test_verify_rejects_a_comparator_roster_that_is_not_config2_constant(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    manifest["comparator_roster"] = list(reversed(_EXPECTED_COMPARATOR_FAMILY))  # order broken
    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    manifest["confirmation_checksum"] = sha256_json(body)  # self-consistent, but wrong roster

    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


# --------------------------------------------------------------------------- #
# verify: malformed stored manifest shape
# --------------------------------------------------------------------------- #


def test_verify_rejects_non_canonical_json_bytes(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    # Valid JSON, but NOT canonical bytes (extra whitespace / key order).
    path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


def test_verify_rejects_wrong_schema(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    manifest["schema"] = "compose_seal_confirmation_manifest_v2"
    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    manifest["confirmation_checksum"] = sha256_json(body)

    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )
