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
    # The COMPLETE §3.2 pre-seal checksum set (exactly 12 keys).
    return {
        "config_checksum": _hex(f"config{salt}"),
        "data_card_checksum": _hex(f"data_card{salt}"),
        "manifest_checksum": _hex(f"manifest{salt}"),
        "sequence_checksum": _hex(f"sequence{salt}"),
        "feature_checksum": _hex(f"feature{salt}"),
        "factor_checksum": _hex(f"factor{salt}"),
        "response_space_checksum": _hex(f"response_space{salt}"),
        "model_checksum": _hex(f"model{salt}"),
        "bundle_checksum": _hex(f"bundle{salt}"),
        "ledger_checksum": _hex(f"ledger{salt}"),
        "pair_index_checksum": _hex(f"pair_index{salt}"),
        "seed_report_checksum": _hex(f"seed_report{salt}"),
    }


def _worker_identity(salt: str = "") -> dict:
    # Per-method {gears, cpa} 6-field ExecutionIdentityLock identity.
    return {
        "gears": {
            "prediction_representation": "delta_log1p",
            "adapter_version": "gears-1.0.0",
            "adapter_sha256": _hex(f"gears_adapter{salt}"),
            "config_sha256": _hex(f"gears_config{salt}"),
            "resource_sha256": _hex(f"gears_resource{salt}"),
            "environment_lock_sha256": _hex(f"gears_env{salt}"),
        },
        # cpa given as the alternate spec-sanctioned form: a content digest.
        "cpa": _hex(f"cpa_worker_identity{salt}"),
    }


def _build_inputs(salt: str = "") -> dict:
    return {
        "run_id": f"run-{salt or 'abc'}",
        "execution_id": _hex(f"execution{salt}"),
        "resolved_run_spec_file_sha256": _hex(f"spec_file{salt}"),
        "approved_git_sha": "a" * 40,
        "git_clean": True,
        "preseal_checksums": _preseal_checksums(salt),
        "selected_hyperparameters": {
            "l3_symmetric_mlp": {"rank": 8, "lr": 0.001, "epochs": 200},
            "l1_bilinear_identifiable": {"ridge": 0.1},
        },
        "worker_identity": _worker_identity(salt),
        "double_pair_count": 42,
        "single_pair_count": 17,
        "ordered_seal_request_checksum": _hex(f"ordered_seal_request{salt}"),
        "futility_status": "CONTINUE",
        "sealed_access_count": 0,
        "forbidden_output_absence": True,
        "accepted_limitations": [
            "K562-internal only; no cross-cell-line transfer claim",
            "retrospective public-data evaluation",
        ],
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
    assert manifest["selected_hyperparameters"] == inputs["selected_hyperparameters"]
    assert manifest["worker_identity"] == inputs["worker_identity"]
    assert manifest["double_pair_count"] == 42
    assert manifest["single_pair_count"] == 17
    assert manifest["ordered_seal_request_checksum"] == inputs["ordered_seal_request_checksum"]
    assert manifest["futility_status"] == "CONTINUE"
    assert manifest["sealed_access_count"] == 0
    assert manifest["forbidden_output_absence"] is True
    assert manifest["accepted_limitations"] == inputs["accepted_limitations"]
    assert manifest["method_roster"] == list(_EXPECTED_METHOD_ROSTER)
    assert manifest["comparator_roster"] == list(_EXPECTED_COMPARATOR_FAMILY)

    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    assert manifest["confirmation_checksum"] == sha256_json(body)


def test_build_binds_the_complete_preseal_checksum_set():
    manifest = build_seal_confirmation_manifest(**_build_inputs())
    assert set(manifest["preseal_checksums"]) == {
        "config_checksum",
        "data_card_checksum",
        "manifest_checksum",
        "sequence_checksum",
        "feature_checksum",
        "factor_checksum",
        "response_space_checksum",
        "model_checksum",
        "bundle_checksum",
        "ledger_checksum",
        "pair_index_checksum",
        "seed_report_checksum",
    }


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
        # A preseal set missing a required member (sequence_checksum) is rejected.
        (
            {
                "preseal_checksums": {
                    k: v for k, v in _preseal_checksums().items() if k != "sequence_checksum"
                }
            },
            "preseal_checksums",
        ),
        ({"selected_hyperparameters": {}}, "selected_hyperparameters"),
        ({"worker_identity": {"gears": _hex("g")}}, "worker_identity"),
        (
            {"worker_identity": {"gears": _hex("g"), "cpa": _hex("c"), "x": _hex("z")}},
            "worker_identity",
        ),
        ({"double_pair_count": -1}, "double_pair_count"),
        ({"single_pair_count": "17"}, "single_pair_count"),
        ({"double_pair_count": True}, "double_pair_count"),
        ({"ordered_seal_request_checksum": "not-hex"}, "ordered_seal_request_checksum"),
        ({"futility_status": "FUTILITY_STOPPED"}, "futility_status"),
        ({"sealed_access_count": 1}, "sealed_access_count"),
        ({"forbidden_output_absence": False}, "forbidden_output_absence"),
        ({"accepted_limitations": "a single string, not a list"}, "accepted_limitations"),
        ({"accepted_limitations": ["ok", 3]}, "accepted_limitations"),
        ({"accepted_limitations": []}, "accepted_limitations"),
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
# verify: the FULL §3.2 extended field schema (self-consistent but invalid)
# --------------------------------------------------------------------------- #


def _reseal(manifest: dict) -> dict:
    """Return *manifest* with a recomputed, self-consistent confirmation_checksum."""
    out = dict(manifest)
    body = {k: v for k, v in out.items() if k != "confirmation_checksum"}
    out["confirmation_checksum"] = sha256_json(body)
    return out


def test_verify_rejects_stored_futility_not_continue(tmp_path):
    inputs = _build_inputs()
    manifest = _reseal(
        {**build_seal_confirmation_manifest(**inputs), "futility_status": "FUTILITY_STOPPED"}
    )
    path = tmp_path / "seal_confirmation_manifest.json"
    path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(ConfirmationError, match="futility_status"):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


def test_verify_rejects_stored_nonzero_sealed_access_count(tmp_path):
    inputs = _build_inputs()
    manifest = _reseal({**build_seal_confirmation_manifest(**inputs), "sealed_access_count": 1})
    path = tmp_path / "seal_confirmation_manifest.json"
    path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(ConfirmationError, match="sealed_access_count"):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


def test_verify_rejects_stored_forbidden_output_present(tmp_path):
    inputs = _build_inputs()
    manifest = _reseal(
        {**build_seal_confirmation_manifest(**inputs), "forbidden_output_absence": False}
    )
    path = tmp_path / "seal_confirmation_manifest.json"
    path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(ConfirmationError, match="forbidden_output_absence"):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


def test_verify_rejects_stored_manifest_missing_a_new_field(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    del manifest["accepted_limitations"]  # drop a required §3.2 field
    manifest = _reseal(manifest)  # self-consistent over the reduced key set
    path = tmp_path / "seal_confirmation_manifest.json"
    path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(ConfirmationError, match="key roster mismatch"):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
        )


def test_verify_rejects_tampered_new_field_breaking_self_checksum(tmp_path):
    inputs = _build_inputs()
    manifest = dict(build_seal_confirmation_manifest(**inputs))
    real_token = manifest["confirmation_checksum"]

    # Mutate a new field WITHOUT recomputing the checksum -> self-checksum broken.
    tampered = dict(manifest)
    tampered["double_pair_count"] = 999
    path = tmp_path / "seal_confirmation_manifest.json"
    path.write_bytes(_canonical_bytes(tampered))

    with pytest.raises(ConfirmationError, match="tampered"):
        verify_seal_confirmation_manifest(path, real_token, reconstruct_inputs=inputs)


def test_verify_rejects_a_diverging_worker_identity_reconstruct_input(tmp_path):
    inputs = _build_inputs()
    manifest = build_seal_confirmation_manifest(**inputs)
    path = tmp_path / "seal_confirmation_manifest.json"
    install_seal_confirmation_manifest(path, manifest)

    changed = dict(inputs)
    changed["worker_identity"] = _worker_identity("DIFFERENT")

    with pytest.raises(ConfirmationError):
        verify_seal_confirmation_manifest(
            path, manifest["confirmation_checksum"], reconstruct_inputs=changed
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
