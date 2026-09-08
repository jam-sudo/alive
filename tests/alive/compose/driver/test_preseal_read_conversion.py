"""Every consumer of the shared digest-bound read converts its error.

`driver.preseal_read` exists because the 2026-08-25 fix bound the pre-seal reads
in ONE loader and missed its siblings -- a lane inside that same file, plus the
config load in three subcommands and two raw byte reads in preflight. Moving the
helper out means there is now one place to fix and none to miss.

That created a new obligation. `PresealBytesError` is classified
UNREACHABLE_FROM_DRIVER, i.e. it is not on `cli._KNOWN_PRESEAL_REJECTIONS` and does
NOT map to exit 10. The classification is only honest while every caller converts
it to an error that IS rostered. If a caller ever forgets, the digest mismatch --
the most safety-relevant rejection in the pre-seal path -- would escape as a bare
`ValueError` and exit 1 as an unrecognised bug.

So the conversion is tested behaviourally, per module, by actually tripping a
mismatch rather than by grepping for an `except` clause. This repository has
recorded that source anchors survive their own mutation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alive.compose.approximation_bias import ApproximationBiasValidationError
from alive.compose.driver import (
    bias_report_preseal,
    phase2a_cmd,
    phase2b_cmd,
    preflight_cmd,
)
from alive.compose.driver import carrier_loader as carrier_mod
from alive.compose.driver.preseal_read import (
    PresealBytesError,
    PresealDescriptorError,
)
from alive.compose.driver.run_spec import PathSha, RunSpecError

_WRONG_SHA = "0" * 64


class _SpecStub:
    """The minimum a `_preseal_bytes` helper touches: `pre_seal[field]`."""

    def __init__(self, field: str, path: str) -> None:
        self.pre_seal = {field: PathSha(path=path, sha256=_WRONG_SHA)}


def _a_file(tmp_path) -> str:
    path = tmp_path / "declared.json"
    path.write_text('{"any": "content"}', encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    ("module", "expected_error"),
    [
        (preflight_cmd, RunSpecError),
        (phase2a_cmd, phase2a_cmd.Phase2aSubcommandError),
        (phase2b_cmd, phase2b_cmd.Phase2bSubcommandError),
    ],
    ids=["preflight_cmd", "phase2a_cmd", "phase2b_cmd"],
)
def test_preseal_bytes_error_never_escapes_its_caller(module, expected_error, tmp_path):
    """A digest mismatch surfaces as the module's OWN rostered error."""
    spec = _SpecStub("config", _a_file(tmp_path))
    with pytest.raises(expected_error) as excinfo:
        module._preseal_bytes(spec, "config")
    assert not isinstance(excinfo.value, PresealBytesError), (
        "the shared error escaped unconverted; it is not on the CLI roster, so it "
        "would exit 1 as an unrecognised bug instead of the contracted pre-seal reject"
    )
    assert "bytes read for consumption" in str(excinfo.value), (
        "the conversion dropped the message that says WHAT diverged"
    )


def test_the_carrier_loader_converts_it_too(tmp_path):
    """The loader the original fix landed in keeps its own contract."""
    declared = PathSha(path=_a_file(tmp_path), sha256=_WRONG_SHA)
    with pytest.raises(RunSpecError) as excinfo:
        carrier_mod._read_verified_bytes(declared, field="config")
    assert not isinstance(excinfo.value, PresealBytesError)


def test_the_descriptor_error_never_escapes_phase2b_either(tmp_path):
    """`verified_descriptor` has the same obligation as `read_verified_bytes`.

    It is also classified UNREACHABLE_FROM_DRIVER, so the sealed-source opener must
    convert it. The relocation on 2026-08-30 moved the implementation out of
    `phase2b_cmd`; this is what proves the delegation did not drop the conversion.
    """
    source = tmp_path / "sealed.h5ad"
    source.write_bytes(b"content")

    with pytest.raises(phase2b_cmd.Phase2bSubcommandError) as excinfo:
        with phase2b_cmd._open_verified_sealed_source(source, _WRONG_SHA):
            pass
    assert not isinstance(excinfo.value, PresealDescriptorError)
    assert "digest mismatch" in str(excinfo.value)


def test_the_bias_lane_converts_the_descriptor_error(tmp_path):
    """The lane that could only be closed with the descriptor, because its
    reconstruction helper lives inside the frozen kernel-isolation closure.

    Calls the module's OWN helper -- an earlier version of this test called
    `verified_descriptor` directly, which exercises no conversion at all and would
    have passed no matter what `bias_report_preseal` did.
    """
    source = tmp_path / "config.yaml"
    source.write_bytes(b"protocol: x\n")
    spec = _SpecStub("config", str(source))

    with pytest.raises(ApproximationBiasValidationError) as excinfo:
        with bias_report_preseal._verified_config_descriptor(spec):
            pass  # pragma: no cover - the context manager raises on entry
    assert not isinstance(excinfo.value, PresealDescriptorError)
    assert "digest mismatch" in str(excinfo.value)


def test_the_bias_lane_accepts_a_str_path(tmp_path):
    """`spec.pre_seal[...].path` is a str.

    The relocation widened `verified_descriptor` to `str | Path` but left the body
    calling Path methods, so this lane raised AttributeError instead of verifying.
    A widened parameter type the body does not honour is not a widened type.
    """
    import hashlib

    source = tmp_path / "config.yaml"
    payload = b"protocol: x\n"
    source.write_bytes(payload)
    spec = _SpecStub("config", str(source))
    spec.pre_seal["config"] = PathSha(path=str(source), sha256=hashlib.sha256(payload).hexdigest())

    with bias_report_preseal._verified_config_descriptor(spec) as descriptor_path:
        assert Path(descriptor_path).read_bytes() == payload


def test_a_matching_digest_returns_the_bytes(tmp_path):
    """Non-vacuity: the conversion path is only interesting if the happy path works."""
    import hashlib

    path = tmp_path / "declared.json"
    payload = b'{"any": "content"}'
    path.write_bytes(payload)
    declared = PathSha(path=str(path), sha256=hashlib.sha256(payload).hexdigest())
    assert carrier_mod._read_verified_bytes(declared, field="config") == payload
