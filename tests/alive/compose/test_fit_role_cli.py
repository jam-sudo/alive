from __future__ import annotations

from scripts.compose.build_fit_role_artifact import build_fit_role_cli


def test_cli_module_importable_and_reports_usage():
    # The CLI is a thin wrapper; invoked with no subcommand it returns non-zero
    # rather than raising, so the pod entry point fails closed.
    assert build_fit_role_cli([]) != 0
