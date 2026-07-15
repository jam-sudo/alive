"""Single pre-seal validation of the config-pinned approximation-bias report.

Both the scientific carrier loader (``carrier_loader``) and the ``phase2b``
subcommand (``phase2b_cmd``) must bind the config-pinned approximation-bias
report to the same evidence-space inputs BEFORE any sealed store is built. This
module owns that binding once so the two pre-seal gates cannot drift: a report
that passed one gate but failed the other would still fail closed (no seal
burned), but keeping two hand-copied ``expected_provenance`` blocks in sync is a
maintenance hazard the v1 spec-review flagged.

It lives at the driver layer (not in the import-light
``alive.compose.approximation_bias`` contract module) because it depends on the
run-spec / config shapes and on ``fit_role.build_response_projection``. Callers
keep their own mode handling and convert the two error classes below into their
own boundary error type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from alive.compose.approximation_bias import (
    ApproximationBiasEvidence,
    basis_config_sha256_from_final_config,
    load_approximation_bias_report,
    measurement_contract_sha256,
)
from alive.compose.config2 import ComposePhase2Config
from alive.compose.driver.run_spec import ResolvedRunSpec
from alive.compose.fit_role import build_response_projection
from alive.provenance import sha256_json

__all__ = [
    "ApproximationBiasDeclarationError",
    "gears_approximation_bias_sha",
    "resolve_pinned_approximation_bias_evidence",
]


class ApproximationBiasDeclarationError(ValueError):
    """Raised when the run spec's ``approximation_bias_report`` declaration is
    inconsistent with the config-pinned SHA (absent, mistyped, or SHA mismatch).

    Distinct from :class:`~alive.compose.approximation_bias.ApproximationBiasValidationError`
    (a report-content / provenance failure) so callers can preserve their
    original two-tier messaging (declaration errors surface verbatim; content
    failures are wrapped as "failed pre-seal validation").
    """


def gears_approximation_bias_sha(config: ComposePhase2Config) -> str | None:
    """Return the config-pinned GEARS approximation-bias report SHA, or ``None``."""
    return next(
        (
            bias
            for name, _representation, bias in config.baseline_representations
            if name == "gears"
        ),
        None,
    )


def resolve_pinned_approximation_bias_evidence(
    spec: ResolvedRunSpec,
    config: ComposePhase2Config,
    *,
    response_artifact: Mapping[str, Any],
) -> ApproximationBiasEvidence | None:
    """Validate the config-pinned report against the run's evidence space, pre-seal.

    Returns the immutable :class:`ApproximationBiasEvidence` snapshot, or ``None``
    when the config pins no GEARS SHA (and the run spec correctly declares none).

    Parameters
    ----------
    spec : ResolvedRunSpec
        The scientific run spec (``spec.scientific`` must be non-``None`` — the
        caller guards mode/scientific-block absence with its own error type).
    config : ComposePhase2Config
        The loaded Phase-2 config; its ``baselines.gears.approximation_bias_report_sha256``
        (via ``baseline_representations``) pins the report.
    response_artifact : mapping
        The loaded response artifact (``response_space``, ``gene_order``,
        ``control_mean``, ``raw_data_sha256``) defining the evaluation space the
        report must bind to.

    Raises
    ------
    ApproximationBiasDeclarationError
        If the config pins a SHA but the run spec declares no report, declares a
        non-mapping, or declares a mismatched SHA (or pins no SHA but the run
        spec declares one).
    ApproximationBiasValidationError
        If the report bytes fail the full v2 integrity / provenance contract.
    OSError
        If the pinned report file is missing or unreadable.
    """
    expected_sha = gears_approximation_bias_sha(config)
    declaration = spec.scientific["approximation_bias_report"]
    if expected_sha is None:
        if declaration is not None:
            raise ApproximationBiasDeclarationError(
                "scientific approximation_bias_report must be null while the config SHA is null"
            )
        return None
    if not isinstance(declaration, Mapping):
        raise ApproximationBiasDeclarationError(
            "scientific config pins an approximation-bias SHA but the run spec carries no report"
        )
    if declaration.get("sha256") != expected_sha:
        raise ApproximationBiasDeclarationError(
            "scientific approximation_bias_report.sha256 does not match the config-pinned SHA"
        )
    projection = build_response_projection(
        response_artifact["response_space"],
        gene_order=response_artifact["gene_order"],
        control_mean=response_artifact["control_mean"],
        raw_data_sha256=response_artifact["raw_data_sha256"],
    )
    basis_sha = basis_config_sha256_from_final_config(
        spec.pre_seal["config"].path,
        expected_report_sha256=expected_sha,
    )
    return load_approximation_bias_report(
        Path(str(declaration.get("path"))),
        expected_content_sha256=expected_sha,
        expected_protocol=config.protocol,
        expected_basis_config_sha256=basis_sha,
        expected_measurement_contract_sha256=measurement_contract_sha256(),
        expected_git_commit=spec.approved_git_sha,
        expected_provenance={
            "norman_source_sha256": response_artifact["raw_data_sha256"],
            "fit_role_artifact_sha256": spec.pre_seal["fit_role_artifact"].sha256,
            "response_projection_sha256": sha256_json(projection),
            "gene_order_sha256": projection["gene_order_sha256"],
            "pca_dim": len(projection["control_mean"]),
            "registered_seeds": list(config.registered_seeds),
        },
    )
