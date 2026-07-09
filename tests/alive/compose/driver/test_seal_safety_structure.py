"""Structural seal-safety assertions for the COMPOSE production driver (spec §4/§2.2).

This is a TEST-ONLY pin. It does NOT exercise a new feature; it STRUCTURALLY
freezes three seal-safety invariants so a future refactor cannot silently break
them. If an assertion here fails, it may reveal a REAL seal leak — treat that as a
cross-task finding to be adjudicated, NOT as a test to be relaxed.

The three pinned invariants (see
docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §4/§2.2):

(a) **Single sealed-store construction point (§4).**
    :class:`~alive.compose.outcome_store.ComposeOutcomeStore` /
    :func:`~alive.compose.outcome_store.build_fixture_outcome_store` are imported
    AND constructed by EXACTLY the ``phase2b`` subcommand path — nowhere else in
    the driver package. Pinned two ways:

    * STRUCTURALLY, via an AST scan of every driver module (docstrings/comments do
      not count — the AST ignores them): ``phase2b_cmd.py`` is the ONLY module that
      imports or references either name. ``carrier_loader.py`` and
      ``fixture_builder.py`` import the ``FIXTURE_CORPUS_V1`` *constant* from the
      same module, which is NOT a store construction and must not trip the scan.
    * At RUNTIME, via a spy on both construction entry points: ``phase2a`` /
      ``preflight`` / ``recover`` construct ZERO stores on real fixture inputs, and
      a full ``phase2b`` fixture chain constructs EXACTLY ONE.

(b) **phase2a/preflight never open the SEALED OUTCOME source (§2.2).**
    The sealed outcome source (``sealed_outcome["source_path"]``) is
    AnnData-parsed ONLY by ``phase2b`` at seal time. It is NOT a blanket
    "0 ``read_h5ad`` calls" rule: ``phase2a`` legitimately reads the DEVELOPMENT
    fit-role ``.h5ad`` during the D2 seed-variability harness (allowed development
    access). The invariant is asserted on the exact ``source_path`` value: any
    h5ad opened during ``phase2a`` / ``preflight`` is the fit-role dev artifact,
    never the sealed source. During ``phase2b`` the sealed source IS opened
    (positive control).

(c) **phase2b store ``audit_path == <run_dir>/audit.jsonl`` (§3.3 step 4).**
    Folded into the invariant-(a) runtime spy: the store the ``phase2b`` path
    constructs carries the recover-critical audit destination, equal to
    ``run_dir / SEAL_AUDIT_FILENAME`` — the exact path ``recover`` reconstructs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import anndata
import pytest

import alive.compose.driver as driver_pkg
import alive.compose.outcome_store as outcome_store_mod
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.phase2b_cmd import (
    PHASE2B_COMPLETE_EXIT,
    run_phase2b_subcommand,
)
from alive.compose.driver.preflight_cmd import run_preflight_subcommand
from alive.compose.driver.recover_cmd import (
    RECOVER_COMPLETE_EXIT,
    run_recover_subcommand,
)
from alive.compose.driver.run_spec import RUN_PRODUCED_BASENAMES
from alive.compose.durable import SEAL_AUDIT_FILENAME

# The two sealed-store construction entry points the §4 invariant is about. The
# store CLASS and its allowlisted fixture FACTORY — NOT the ``FIXTURE_CORPUS_V1``
# attestation constant that ``carrier_loader`` / ``fixture_builder`` import from
# the same module (a constant is data, not a store construction).
_STORE_NAMES = frozenset({"ComposeOutcomeStore", "build_fixture_outcome_store"})

#: The complete driver-package module roster the structural scan covers. Every
#: ``.py`` in the package must appear here (a drift guard asserts this), so a
#: newly-added module (e.g. a future carrier variant) cannot escape the scan.
_DRIVER_MODULES = frozenset(
    {
        "__init__",
        "carrier_loader",
        "cli",
        "confirmation",
        "fixture_builder",
        "identity_lock",
        "pair_index",
        "phase2a_cmd",
        "phase2b_cmd",
        "preflight_cmd",
        "recover_cmd",
        "run_dir_state",
        "run_spec",
    }
)

#: The ONE module permitted to import/construct the sealed store (§4).
_SOLE_STORE_MODULE = "phase2b_cmd"

_CONFIRMATION = RUN_PRODUCED_BASENAMES["seal_confirmation_manifest"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _driver_dir() -> Path:
    """The on-disk driver package directory (source of the AST scan)."""
    return Path(driver_pkg.__file__).parent


def _module_references_store(module_name: str) -> list[str]:
    """AST-scan one driver module for real imports/uses of a store entry point.

    Parses the module source and walks the AST — so docstrings, comments and
    string literals that merely MENTION the names (several modules reference them
    in prose) are NOT counted. Only genuine ``from ... import <name>`` /
    ``import <name>`` statements and ``Name`` / ``Attribute`` references to the
    two store entry points are returned.

    Returns
    -------
    list[str]
        Human-readable ``"<kind> <name> @L<lineno>"`` findings (empty if the
        module neither imports nor references either store entry point).
    """
    path = _driver_dir() / f"{module_name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _STORE_NAMES:
                    findings.append(f"IMPORT-FROM {node.module}.{alias.name} @L{node.lineno}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _STORE_NAMES:
                    findings.append(f"IMPORT {alias.name} @L{node.lineno}")
        elif isinstance(node, ast.Name) and node.id in _STORE_NAMES:
            findings.append(f"NAME-USE {node.id} @L{node.lineno}")
        elif isinstance(node, ast.Attribute) and node.attr in _STORE_NAMES:
            findings.append(f"ATTR-USE .{node.attr} @L{node.lineno}")
    return findings


def _run_preseal(tmp_path: Path):
    """Build the fixture and run the REAL ``phase2a`` then ``preflight`` (no mocks)."""
    fx = build_compose_fixture(tmp_path)
    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    assert run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    return fx


def _confirmation_token(run_dir: Path) -> str:
    """The FULL ``confirmation_checksum`` of the installed manifest (the token)."""
    import json

    return json.loads((run_dir / _CONFIRMATION).read_bytes())["confirmation_checksum"]


class _StoreSpy:
    """Records every sealed-store construction and each captured ``audit_path``.

    Wraps both §4 construction entry points: ``ComposeOutcomeStore.__init__`` (also
    invoked by ``FixtureOutcomeStore`` via ``super().__init__``) and the allowlisted
    ``build_fixture_outcome_store`` factory. ``audit_paths`` captures the store's
    resolved ``_audit_path`` at each construction (invariant (c)).
    """

    def __init__(self) -> None:
        self.init_count = 0
        self.factory_count = 0
        self.audit_paths: list[Path] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_init = outcome_store_mod.ComposeOutcomeStore.__init__
        real_factory = outcome_store_mod.build_fixture_outcome_store

        def _spy_init(store, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            real_init(store, *args, **kwargs)
            self.init_count += 1
            self.audit_paths.append(Path(store._audit_path))

        def _spy_factory(*args, **kwargs):  # noqa: ANN002, ANN003
            self.factory_count += 1
            return real_factory(*args, **kwargs)

        monkeypatch.setattr(outcome_store_mod.ComposeOutcomeStore, "__init__", _spy_init)
        monkeypatch.setattr(outcome_store_mod, "build_fixture_outcome_store", _spy_factory)
        # phase2b imports the factory by name into its own namespace, so patch that
        # bound reference too (an ``import X from Y`` binds the function, not module).
        import alive.compose.driver.phase2b_cmd as phase2b_mod

        monkeypatch.setattr(phase2b_mod, "build_fixture_outcome_store", _spy_factory)


class _ReadH5adSpy:
    """Records every path passed to ``anndata.read_h5ad`` (all call sites).

    ``phase2b`` calls ``anndata.read_h5ad`` (module-level import) and the phase2a
    D2 harness calls ``ad.read_h5ad`` (a local ``import anndata as ad``); both
    resolve the SAME module attribute at call time, so one patch on
    ``anndata.read_h5ad`` observes every driver-reachable open.
    """

    def __init__(self) -> None:
        self.opened: list[Path] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = anndata.read_h5ad

        def _spy(filename, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            self.opened.append(Path(filename))
            return real(filename, *args, **kwargs)

        monkeypatch.setattr(anndata, "read_h5ad", _spy)


# --------------------------------------------------------------------------- #
# Invariant (a) — structural: phase2b_cmd is the SOLE store import/use site (§4)
# --------------------------------------------------------------------------- #
def test_scan_roster_matches_on_disk_modules() -> None:
    """Drift guard: the scan roster equals the driver package's ``.py`` set.

    If a new module is added without being added to ``_DRIVER_MODULES``, the
    structural scan would silently skip it — so pin the roster to the on-disk
    reality (this is what lets the §4 scan claim it covers the WHOLE package).
    """
    on_disk = {p.stem for p in _driver_dir().glob("*.py")}
    assert on_disk == set(_DRIVER_MODULES), (
        "driver package modules drifted from the structural-scan roster; "
        f"on_disk-only={sorted(on_disk - set(_DRIVER_MODULES))} "
        f"roster-only={sorted(set(_DRIVER_MODULES) - on_disk)}"
    )


def test_only_phase2b_imports_or_constructs_the_store() -> None:
    """§4: EXACTLY ``phase2b_cmd`` imports/references the sealed-store entry points.

    Every OTHER driver module (including the recently-added ``carrier_loader``,
    which imports only the ``FIXTURE_CORPUS_V1`` constant) must have ZERO real AST
    references — a genuine store import/construction anywhere else is a §4 seal
    leak, NOT something to paper over here.
    """
    offenders = {
        module: refs
        for module in _DRIVER_MODULES
        if module != _SOLE_STORE_MODULE and (refs := _module_references_store(module))
    }
    assert offenders == {}, (
        "the sealed store must be imported/constructed by phase2b_cmd ALONE (§4); "
        f"unexpected references found in: {offenders}"
    )

    # And phase2b_cmd genuinely DOES import + construct it (the scan is not vacuous).
    phase2b_refs = _module_references_store(_SOLE_STORE_MODULE)
    assert any(ref.startswith("IMPORT-FROM") for ref in phase2b_refs)
    assert any("ComposeOutcomeStore" in ref for ref in phase2b_refs)
    assert any("build_fixture_outcome_store" in ref for ref in phase2b_refs)


# --------------------------------------------------------------------------- #
# Invariant (a) — runtime: phase2a / preflight / recover construct ZERO stores
# --------------------------------------------------------------------------- #
def test_phase2a_and_preflight_construct_no_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4 runtime spy: neither ``phase2a`` nor ``preflight`` builds any store."""
    fx = build_compose_fixture(tmp_path)
    spy = _StoreSpy()
    spy.install(monkeypatch)

    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    assert run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0

    assert spy.init_count == 0, "phase2a/preflight constructed a ComposeOutcomeStore (§4 leak)"
    assert spy.factory_count == 0, "phase2a/preflight called build_fixture_outcome_store (§4 leak)"


def test_recover_constructs_no_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 runtime spy: ``recover`` (a thin post-seal wrapper) builds no store.

    Runs the full ``phase2a → preflight → phase2b`` chain to obtain a genuine burned
    audit + durable outputs, then installs the spy FRESH and runs the VERIFY-ONLY
    ``recover`` — which must touch no store at all.
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)
    assert (
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
        == PHASE2B_COMPLETE_EXIT
    )

    # Spy installed AFTER phase2b, so only recover's own constructions are counted.
    spy = _StoreSpy()
    spy.install(monkeypatch)
    assert run_recover_subcommand(run_dir=fx.run_dir) == RECOVER_COMPLETE_EXIT
    assert spy.init_count == 0, "recover constructed a ComposeOutcomeStore (§4 leak)"
    assert spy.factory_count == 0, "recover called build_fixture_outcome_store (§4 leak)"


# --------------------------------------------------------------------------- #
# Invariant (a)+(c) — runtime: phase2b builds EXACTLY ONE store at run_dir/audit
# --------------------------------------------------------------------------- #
def test_phase2b_constructs_exactly_one_store_with_run_bound_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4 + §3.3 step 4: ``phase2b`` builds EXACTLY ONE store, audit run-bound (c).

    The full fixture chain constructs one and only one sealed store, via the
    allowlisted fixture factory, and its ``_audit_path`` is exactly
    ``run_dir / SEAL_AUDIT_FILENAME`` (the recover-critical destination).
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    spy = _StoreSpy()
    spy.install(monkeypatch)
    assert (
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
        == PHASE2B_COMPLETE_EXIT
    )

    # EXACTLY ONE construction, via the allowlisted fixture factory (fixture mode).
    assert spy.init_count == 1, f"expected 1 store construction, got {spy.init_count}"
    assert spy.factory_count == 1, f"expected 1 fixture-factory call, got {spy.factory_count}"

    # Invariant (c): the SEAL_AUDIT_FILENAME constant pins the recover-critical path.
    assert spy.audit_paths == [fx.run_dir / SEAL_AUDIT_FILENAME]


# --------------------------------------------------------------------------- #
# Invariant (b) — phase2a/preflight never AnnData-parse the SEALED OUTCOME source
# --------------------------------------------------------------------------- #
def test_phase2a_preflight_do_not_open_the_outcome_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.2: the sealed ``source_path`` is never opened by ``phase2a`` / ``preflight``.

    NOTE (test naming): this function must NOT contain the substring ``"sealed"`` —
    pytest derives ``tmp_path`` from the function name, and the baseline-fit guard
    (``_assert_no_sealed_reference``) fails closed on ANY path containing a sealed
    token. The fit-role ``.h5ad`` lives under ``tmp_path``, so a ``"sealed"`` in the
    name would spuriously trip the guard during phase2a's D2 fit — unrelated to the
    invariant under test.

    This is NOT a blanket "0 ``read_h5ad``" assertion — ``phase2a`` legitimately
    reads the DEVELOPMENT fit-role ``.h5ad`` during the D2 seed-variability harness
    (allowed development access). The pinned invariant is on the exact
    ``source_path``: the SEALED source is never among the h5ad opened by
    ``phase2a`` / ``preflight``, while the fit-role dev artifact may be.
    """
    fx = build_compose_fixture(tmp_path)
    sealed_source = Path(fx.sealed_outcome["source_path"]).resolve()

    spy = _ReadH5adSpy()
    spy.install(monkeypatch)

    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    assert run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0

    opened = {p.resolve() for p in spy.opened}

    # PRIMARY assertion (the invariant): the SEALED OUTCOME source is never opened
    # by phase2a / preflight.
    assert sealed_source not in opened, (
        "phase2a/preflight opened the SEALED OUTCOME source (§2.2 leak); "
        f"sealed={sealed_source} opened={sorted(str(p) for p in opened)}"
    )

    # DEFENSE-IN-DEPTH: every h5ad the pre-seal path DOES open is a DEVELOPMENT
    # fit-role artifact — either the base fit-role file or a D2 seed-variability
    # fold derivative carved from it (``d2_seed_variability_folds/``, all under the
    # fit-role's own directory). This is the allowed development access; the sealed
    # source lives elsewhere. Pinning the dev tree (not a single file) keeps the
    # assertion correct as the D2 harness materializes per-fold train-only subsets.
    fit_role_path = Path(fx.response_artifact["fit_role_spec"].path).resolve()
    dev_tree = fit_role_path.parent
    for opened_path in opened:
        assert opened_path == fit_role_path or dev_tree in opened_path.parents, (
            "phase2a/preflight opened an h5ad outside the development fit-role tree "
            f"(expected the fit-role base {fit_role_path} or a D2 fold under "
            f"{dev_tree}); got {opened_path}"
        )
        assert opened_path != sealed_source


def test_phase2b_opens_the_outcome_source_positive_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.2 positive control: ``phase2b`` DOES AnnData-parse the sealed source.

    Confirms the invariant-(b) spy actually observes a sealed-source open when one
    is expected — so the negative assertion above is not vacuously true because the
    spy misses the call site.

    NOTE (test naming): ``"sealed"`` is kept out of this function name too — it runs
    phase2a (via ``_run_preseal``), whose D2 baseline fit fails closed on any
    ``tmp_path`` carrying a sealed token (see the sibling test's note).
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)
    sealed_source = Path(fx.sealed_outcome["source_path"]).resolve()

    spy = _ReadH5adSpy()
    spy.install(monkeypatch)
    assert (
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
        == PHASE2B_COMPLETE_EXIT
    )

    opened = {p.resolve() for p in spy.opened}
    assert sealed_source in opened, (
        "phase2b did not open the sealed source — the (b) spy would miss a real "
        f"leak; sealed={sealed_source} opened={sorted(str(p) for p in opened)}"
    )
