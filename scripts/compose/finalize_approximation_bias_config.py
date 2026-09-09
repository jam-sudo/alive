#!/usr/bin/env python
"""LOCAL one-way finalization tool for the GEARS approximation-bias config binding.

Task 6 of the COMPOSE approximation-bias v1 implementation plan
(``docs/superpowers/plans/2026-07-13-compose-approximation-bias-implementation.md``;
design spec ``docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md``
§4 "one-way provenance"). Tasks 1-5 (``measure_pseudobulk_approximation_bias.py``) MEASURE
the pseudobulk-approximation bias and write a
``compose_approximation_bias_report_v4`` report bound to a bias-NULL basis
config (``report["provenance"]["basis_config_sha256"]``). This tool does the
opposite direction, exactly once: it binds that completed report's OWN
content SHA into a copy of the basis config
(``baselines.gears.approximation_bias_report_sha256``) — and nothing else.

This does not measure anything, does not run on real Norman data, does not
import ``gears``/``cpa``, opens no seal, and touches no outcome store. It is a
pure, local, deterministic config transform:

    finalize_bias_config(basis, report) -> final

that is mechanically proven, every call, to have changed EXACTLY the one
registered leaf (:func:`_assert_single_leaf_diff`) and to never let the
resulting final config's own SHA leak back into the report it was derived
from (:func:`_assert_no_final_sha_leak`) — the report already exists and is
immutable by the time this tool runs, so a final config whose SHA appeared
inside that report would be an impossible cycle (design spec §4).

``config2.py`` (``src/alive/compose/config2.py``) is touched READ-ONLY here:
this module only imports ``alive.provenance.sha256_json``, the SAME function
``config2.py:735`` uses to compute ``ComposePhase2Config.config_sha256``, so
the ``basis_sha``/``final_sha`` this tool computes are byte-identical to what
the real loader would compute for the same YAML text. The approximation-bias
requirement is deliberately NOT added to
``config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS`` — doing so would make a future
finalized config's identity get folded back into activation evidence that
itself feeds this same report, recreating the forbidden cycle this tool
exists to avoid (see
``tests/alive/compose/test_finalize_approximation_bias_config.py::test_bias_requirement_not_config_bound``).

The report's ``provenance`` is NOT trusted for the Probe-A facts it declares.
Every call re-opens the three Probe-A byte sources (admission, registration,
verification receipt) through the SAME validators the producer used, checks
their digests against the report's three ``probe_a_*_sha256`` fields, and
refuses unless the representation the evidence ACTUALLY validated both admits
this method and is the one the report declares. Under the committed Probe-A
owner policy (``configs/compose_gears_probe_a_owner_policy_v1.json``) the bridge
validates ``log_normalized_pseudobulk`` while every admissible report must
declare ``raw_pseudobulk_approximation``, so this tool admits NOTHING today: the
success path is POD-GATED behind the R1 representation decision
(``docs/superpowers/COMPOSE-SEAL-READINESS.md:118``). That is the honest state
of the evidence, not a defect in the tool.

Usage
-----
    uv run python scripts/compose/finalize_approximation_bias_config.py \\
        --basis-config configs/compose_k562_v1_phase2.yaml \\
        --report artifacts/compose/approximation_bias_report.json \\
        --probe-a-evidence artifacts/compose/probe_a_admission.json \\
        --probe-a-registration artifacts/compose/probe_a_registration.json \\
        --probe-a-verification artifacts/compose/probe_a_verification.json \\
        --out artifacts/compose/compose_k562_v1_phase2_bias_finalized.yaml
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from alive.compose.approximation_bias import (
    REPRESENTATION,
    bridge_admits,
    load_probe_a_evidence,
    measurement_contract_sha256,
    probe_a_from_evidence,
    validate_approximation_bias_report,
)
from alive.provenance import sha256_file, sha256_json

#: The ONLY leaf this tool is ever permitted to change (design spec §4 / brief
#: Task 6): ``basis["baselines"]["gears"]["approximation_bias_report_sha256"]``.
_BIAS_LEAF_PATH: tuple[str, ...] = ("baselines", "gears", "approximation_bias_report_sha256")


def _leaf_diff(a: Any, b: Any, path: tuple[str, ...] = ()) -> list[list[str]]:
    """Recursively enumerate every leaf path at which ``a`` and ``b`` differ.

    A "leaf" is any node that is not itself a ``dict``: lists, scalars, and
    ``None`` are compared atomically via ``!=`` and never recursed into, so a
    real content change anywhere inside nested dicts surfaces as exactly one
    entry in the returned list, keyed by its full key-path from the root. A
    key present in only one of ``a``/``b`` is also reported as one leaf at
    that key's path (its subtree is not further expanded).

    Parameters
    ----------
    a, b : object
        The two structures to compare (typically the parsed basis config and
        a candidate finalized config).
    path : tuple of str
        Internal recursion accumulator; callers should omit it.

    Returns
    -------
    list of list of str
        Every differing leaf's key-path, each as a list of string keys from
        the root. Empty when ``a == b`` at every leaf.
    """
    diffs: list[list[str]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub_path = path + (str(key),)
            if key not in a or key not in b:
                diffs.append(list(sub_path))
            else:
                diffs.extend(_leaf_diff(a[key], b[key], sub_path))
    elif a != b:
        diffs.append(list(path))
    return diffs


def _assert_single_leaf_diff(basis: Mapping, final: Mapping) -> None:
    """Fail closed unless ``final`` differs from ``basis`` at EXACTLY one leaf.

    Mechanically proves the "one-way, single-leaf" finalization invariant
    (brief Task 6 (iv)): a recursive leaf-path diff of ``basis`` vs ``final``
    must contain exactly one entry, and it must be
    ``list(_BIAS_LEAF_PATH)``. Any other outcome — zero diffs, the wrong leaf,
    or an extra leaf anywhere else in the config — raises :class:`ValueError`
    rather than silently finalizing an over-broad config change.

    Parameters
    ----------
    basis : Mapping
        The bias-NULL basis config as loaded from YAML.
    final : Mapping
        The candidate finalized config.

    Raises
    ------
    ValueError
        If the leaf-diff set is anything other than exactly
        ``[list(_BIAS_LEAF_PATH)]``.
    """
    diff_paths = _leaf_diff(basis, final)
    expected = [list(_BIAS_LEAF_PATH)]
    if diff_paths != expected:
        raise ValueError(
            f"finalize_bias_config: expected exactly one leaf diff at {expected}, got {diff_paths}"
        )


def _assert_no_final_sha_leak(final: Mapping, report: Mapping) -> None:
    """Fail closed if the finalized config's own SHA appears inside the report.

    The report already exists (it was written by the measurement script
    before this tool ever runs) and is treated as immutable input here, so a
    finalized config whose ``sha256_json`` shows up as a literal substring
    inside that report's JSON would mean the report embeds the identity of a
    config that itself embeds the report — an impossible one-way-provenance
    cycle (design spec §4).

    Parameters
    ----------
    final : Mapping
        The candidate finalized config (already proven single-leaf via
        :func:`_assert_single_leaf_diff`).
    report : Mapping
        The parsed approximation-bias report this config is being bound to.

    Raises
    ------
    ValueError
        If ``sha256_json(final)`` is a substring of ``json.dumps(report)``.
    """
    final_sha = sha256_json(final)
    if final_sha in json.dumps(report):
        raise ValueError(
            "finalize_bias_config: final config SHA appears inside the report JSON -- "
            "one-way binding invariant violated (a report must never embed the SHA of "
            "a config that itself embeds that report's SHA)"
        )


def _write_single_leaf(basis: dict, report_content_sha: str) -> dict:
    """Return a deep copy of ``basis`` with ONLY the registered bias leaf set.

    The pure leaf write, carrying NO guards of its own:
    :func:`finalize_bias_config` runs every admission guard BEFORE calling it.
    It is a named function rather than three inline lines because the ONE
    authoritative content-SHA recipe it applies -- ``sha256_file`` of the exact
    on-disk report bytes, the same recipe ``phase2b`` re-verifies -- must stay
    provable end to end even though the guarded path above it cannot succeed
    under today's Probe-A owner policy (see the module docstring). The
    metric -> recipe -> loader round-trip in
    ``tests/alive/compose/test_phase2b.py`` calls it directly for exactly that.

    Parameters
    ----------
    basis : dict
        The bias-NULL basis config as loaded from YAML.
    report_content_sha : str
        ``sha256_file`` of the completed report's exact on-disk bytes.

    Returns
    -------
    dict
        A deep copy of ``basis`` with ``baselines.gears``
        ``.approximation_bias_report_sha256`` set to ``report_content_sha``.
    """
    final = copy.deepcopy(basis)
    final["baselines"]["gears"]["approximation_bias_report_sha256"] = report_content_sha
    return final


def finalize_bias_config(
    *,
    basis_config_path: str | Path,
    report_path: str | Path,
    probe_a_evidence_path: str | Path,
    probe_a_registration_path: str | Path,
    probe_a_verification_path: str | Path,
) -> dict:
    """Bind a completed approximation-bias report's content SHA into its basis config.

    Reads the bias-NULL YAML config at ``basis_config_path`` and the
    ``compose_approximation_bias_report_v4`` JSON report at ``report_path``,
    validates the report is genuinely bound to (and the basis is eligible
    for) this finalization, and returns a deep copy of the basis config with
    ONLY ``baselines.gears.approximation_bias_report_sha256`` set to the
    report's content SHA.

    In order:

    1. ``basis_sha = sha256_json(yaml.safe_load(basis_config_path))`` — the
       SAME hash :data:`alive.compose.config2.ComposePhase2Config.config_sha256`
       computes for the identical YAML text.
    2. The basis must be bias-NULL:
       ``basis["baselines"]["gears"]["approximation_bias_report_sha256"] is None``
       — finalizing an already-finalized basis would silently discard the
       previously-recorded SHA.
    3. The report must be bound to this exact basis:
       ``report["provenance"]["basis_config_sha256"] == basis_sha``.
    4. :func:`_write_single_leaf` deep-copies the basis and sets ONLY the one
       registered leaf to
       ``sha256_file(report_path)`` — the SHA-256 of the EXACT on-disk report
       bytes the metric script wrote (``_canonical_json(report) + "\n"``, WITH
       the trailing newline). This is the single authoritative content-SHA
       recipe: the metric writes those bytes, this tool pins
       ``sha256_file`` of them, and ``phase2b`` re-verifies the pinned config
       SHA with the SAME ``sha256_file`` — so all three agree byte-for-byte.
       (It is deliberately NOT the report's internal ``self_checksum``, which
       is a different quantity — the SHA over ``report − self_checksum`` with
       no trailing newline.)
    5. :func:`_assert_single_leaf_diff` mechanically proves nothing else
       changed.
    6. :func:`_assert_no_final_sha_leak` proves the resulting final config's
       SHA does not appear inside the report (the one-way/no-cycle
       invariant).

    Between 3. and 4. the report's Probe-A *self-declaration* is checked against
    the Probe-A BYTES: the three paths are mandatory, their ``sha256_file``
    digests must equal the report's ``probe_a_evidence_sha256`` /
    ``probe_a_registration_sha256`` / ``probe_a_verification_sha256``, the
    admission is revalidated through :func:`load_probe_a_evidence` /
    :func:`probe_a_from_evidence` (no new trust assumption is created here --
    the same validators the producer ran), the representation that bridge
    actually validated must ADMIT this method (:func:`bridge_admits`), and it
    must be the representation the report declares. The three paths are required
    keyword arguments on purpose: an optional guard is bypassed by omission.

    Parameters
    ----------
    basis_config_path : str or Path
        Path to the bias-NULL Phase-2 YAML config.
    report_path : str or Path
        Path to the completed ``compose_approximation_bias_report_v4`` JSON
        report.
    probe_a_evidence_path : str or Path
        Path to the Probe-A admission JSON whose bytes the report pins in
        ``provenance.probe_a_evidence_sha256``. REQUIRED.
    probe_a_registration_path : str or Path
        Path to the owner-frozen Probe-A registration JSON. REQUIRED.
    probe_a_verification_path : str or Path
        Path to the offline Probe-A verification receipt JSON. REQUIRED.

    Returns
    -------
    dict
        The finalized config: a deep copy of the basis config with exactly
        ``baselines.gears.approximation_bias_report_sha256`` set.

    Raises
    ------
    ValueError
        If the basis does not parse to a mapping, the basis is not
        bias-NULL, the report is not bound to this basis, any of the three
        Probe-A byte sources disagrees with the digest the report declares for
        it, the Probe-A bridge does not admit this method, the report declares a
        representation the evidence did not validate, the leaf-diff guard fires,
        or the one-way SHA-leak guard fires.
    ApproximationBiasValidationError
        If the report itself, or any of the three Probe-A artifacts, fails the
        shared integrity contracts.
    """
    basis = yaml.safe_load(Path(basis_config_path).read_text(encoding="utf-8"))
    if not isinstance(basis, dict):
        raise ValueError("finalize_bias_config: basis config must parse to a YAML mapping")
    basis_sha = sha256_json(basis)

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("finalize_bias_config: report must parse to a JSON object")

    baselines = basis.get("baselines")
    gears = baselines.get("gears") if isinstance(baselines, dict) else None
    if not isinstance(gears, dict) or "approximation_bias_report_sha256" not in gears:
        raise ValueError(
            "finalize_bias_config: basis config is missing "
            "baselines.gears.approximation_bias_report_sha256"
        )
    if gears["approximation_bias_report_sha256"] is not None:
        raise ValueError(
            "finalize_bias_config: basis config is not bias-NULL "
            "(baselines.gears.approximation_bias_report_sha256 must be null before "
            "finalization -- it appears to already carry a recorded bias report)"
        )

    provenance = report.get("provenance")
    report_basis_sha = (
        provenance.get("basis_config_sha256") if isinstance(provenance, dict) else None
    )
    if report_basis_sha != basis_sha:
        raise ValueError(
            "finalize_bias_config: report.provenance.basis_config_sha256 does not match "
            "sha256_json(basis_config) -- this report is not bound to this basis config"
        )

    validate_approximation_bias_report(
        report,
        expected_protocol=str(basis.get("protocol")),
        expected_basis_config_sha256=basis_sha,
        expected_measurement_contract_sha256=measurement_contract_sha256(),
        expected_provenance={
            "registered_seeds": list(basis.get("seeds", {}).get("registered_seeds", [])),
            # R1: only a report whose Probe-A bridge validated THIS representation may be
            # turned into a config leaf (design spec, "Probe-A candidate correction").
            "probe_a_output_representation": REPRESENTATION,
        },
    )

    provenance = report["provenance"]
    for path, key, field in (
        (probe_a_evidence_path, "probe_a_evidence_sha256", "Probe-A admission"),
        (probe_a_registration_path, "probe_a_registration_sha256", "Probe-A registration"),
        (probe_a_verification_path, "probe_a_verification_sha256", "Probe-A verification"),
    ):
        if sha256_file(path) != provenance[key]:
            raise ValueError(f"finalize_bias_config: {field} bytes do not match the report's {key}")
    # Re-run the SAME validators the producer ran -- so that binding the report to
    # these bytes creates no new trust assumption of its own.
    evidence = load_probe_a_evidence(
        probe_a_evidence_path,
        registration_path=probe_a_registration_path,
        verification_path=probe_a_verification_path,
        expected_git_commit=str(provenance["git_commit"]),
        expected_registration_sha256=str(provenance["probe_a_registration_sha256"]),
        expected_verification_sha256=str(provenance["probe_a_verification_sha256"]),
    )
    probe_a = probe_a_from_evidence(
        evidence,
        expected_git_commit=str(provenance["git_commit"]),
        expected_registration_sha256=str(provenance["probe_a_registration_sha256"]),
        expected_verification_sha256=str(provenance["probe_a_verification_sha256"]),
    )
    bridged = str(probe_a["output_bridge"]["representation"])
    if not bridge_admits(method=REPRESENTATION, probe_representation=bridged):
        raise ValueError(
            "finalize_bias_config: the Probe-A bridge validated "
            f"{bridged!r}, which does not admit a {REPRESENTATION!r} report"
        )
    if bridged != str(provenance["probe_a_output_representation"]):
        raise ValueError(
            "finalize_bias_config: the report's probe_a_output_representation "
            f"({provenance['probe_a_output_representation']!r}) is not what the Probe-A "
            f"evidence actually validated ({bridged!r})"
        )

    # The ONE authoritative content-SHA recipe: the SHA-256 of the EXACT on-disk
    # report bytes (canonical JSON + trailing newline, as the metric wrote them).
    # phase2b re-verifies the pinned config SHA with this same sha256_file, so
    # metric-writes → finalize-pins → phase2b-verifies never disagree by a byte.
    report_content_sha = sha256_file(report_path)
    final = _write_single_leaf(basis, report_content_sha)

    _assert_single_leaf_diff(basis, final)
    _assert_no_final_sha_leak(final, report)

    return final


def main(argv: list[str] | None = None) -> int:
    """Thin CLI: read the config, the report and the three Probe-A byte sources.

    The three ``--probe-a-*`` paths are ``required=True``: an optional evidence
    binding is a guard bypassed by omission.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments (excluding the program name); defaults to
        ``sys.argv[1:]`` when ``None``.

    Returns
    -------
    int
        Process exit code (``0`` on success; :func:`finalize_bias_config`
        raises on any validation failure, so a nonzero/exception exit means
        no ``--out`` file is written).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basis-config", required=True, type=Path, help="bias-NULL YAML config")
    parser.add_argument(
        "--report", required=True, type=Path, help="completed approximation_bias_report_v4 JSON"
    )
    parser.add_argument(
        "--probe-a-evidence", required=True, type=Path, help="Probe-A admission JSON"
    )
    parser.add_argument(
        "--probe-a-registration", required=True, type=Path, help="Probe-A registration JSON"
    )
    parser.add_argument(
        "--probe-a-verification",
        required=True,
        type=Path,
        help="Probe-A verification receipt JSON",
    )
    parser.add_argument("--out", required=True, type=Path, help="finalized config YAML output")
    args = parser.parse_args(argv)

    final = finalize_bias_config(
        basis_config_path=args.basis_config,
        report_path=args.report,
        probe_a_evidence_path=args.probe_a_evidence,
        probe_a_registration_path=args.probe_a_registration,
        probe_a_verification_path=args.probe_a_verification,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(final, sort_keys=False), encoding="utf-8")
    print(
        f"wrote {args.out}: baselines.gears.approximation_bias_report_sha256="
        f"{final['baselines']['gears']['approximation_bias_report_sha256']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
