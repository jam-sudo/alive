"""The driver's exit-code contract, enumerated by machine (driver design spec 1.1).

Why this file exists. The registered contract says ``main`` returns ``0`` on
success, ``10`` on a pre-seal rejection, ``20`` on ``FUTILITY_STOPPED``, ``30`` on
a post-seal non-``COMPLETE`` termination, and -- registered 2026-08-01 -- ``1``
when an exception outside :data:`~alive.compose.driver.cli._KNOWN_PRESEAL_REJECTIONS`
propagates, which means a driver BUG and not a contracted outcome. Twice now this
repository has enumerated a safety-relevant roster BY HAND (the pre-seal rejection
roster, and the kernel-isolation closure) and twice the hand-count missed entries.
So the enumeration here is mechanical: every exception class defined anywhere under
``src/alive`` must appear in :data:`_CLASSIFICATION` with a justification, and the
tests fail closed -- telling the reader to classify a new class, never to delete
the check.

The three structural facts the classification rests on:

1. ``phase2a`` and ``preflight`` cannot construct a sealed store at all (spec 4),
   so every exception they raise is pre-seal by construction.
2. ``phase2b_cmd`` wraps its library dispatch in ``except Exception`` and branches
   on ``_seal_consumed(audit_path)`` -- FILESYSTEM evidence, not the exception type
   -- returning ``30`` when the seal was consumed and re-raising otherwise. So an
   exception that reaches the CLI from ``phase2b`` is pre-seal too.
3. ``recover`` opens no seal.

Together those mean admitting a type to the roster cannot mislabel a consumed seal
as a pre-seal rejection. The risk that remains is the opposite one: admitting a
BUILTIN base would map unclassified internal-invariant failures to a contracted
rejection, which is why the spec forbids it and
:func:`test_the_roster_admits_no_builtin_base` pins it.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from alive.compose.driver import cli

_REPO = Path(__file__).resolve().parents[4]
_SRC = _REPO / "src"
_ROOT_MODULE = "alive.compose.driver.cli"

#: Builtin exception bases a project class may inherit from. Used only to seed the
#: transitive "is this class an exception?" closure below -- never as a roster entry.
_BUILTIN_BASES = frozenset(
    {
        "BaseException",
        "Exception",
        "ValueError",
        "RuntimeError",
        "TypeError",
        "KeyError",
        "OSError",
        "LookupError",
        "ArithmeticError",
    }
)

PRESEAL_REJECTION = "PRESEAL_REJECTION"
POSTSEAL = "POSTSEAL"
BUG = "BUG"
UNREACHABLE_FROM_DRIVER = "UNREACHABLE_FROM_DRIVER"

_VALID_CLASSIFICATIONS = frozenset({PRESEAL_REJECTION, POSTSEAL, BUG, UNREACHABLE_FROM_DRIVER})

#: ``module::ClassName -> (classification, justification)``. Keyed by module AND
#: name because names repeat across modules (two ``ConfigError``, two
#: ``MetricError``). Every entry's justification says WHY, in one line, so a
#: reviewer can refute it without re-deriving the call graph.
_CLASSIFICATION: dict[str, tuple[str, str]] = {
    # ---- driver layer: carrier assembly and the four subcommands ----------------
    "alive.compose.driver.run_spec::RunSpecError": (
        PRESEAL_REJECTION,
        "ResolvedRunSpec canonical-bytes/schema/self-checksum/path-policy rejection.",
    ),
    "alive.compose.driver.carrier_loader::UnsupportedModeError": (
        PRESEAL_REJECTION,
        "RunSpecError subclass; covered by the roster's RunSpecError entry.",
    ),
    "alive.compose.driver.run_dir_state::RunDirStateError": (
        PRESEAL_REJECTION,
        "Run-directory entry roster violated, checked before any fit.",
    ),
    "alive.compose.driver.phase2a_cmd::Phase2aSubcommandError": (
        PRESEAL_REJECTION,
        "phase2a orchestration rejection; phase2a can construct no sealed store.",
    ),
    "alive.compose.driver.preflight_cmd::PreflightSubcommandError": (
        PRESEAL_REJECTION,
        "preflight orchestration rejection; preflight constructs no store at all.",
    ),
    "alive.compose.driver.phase2b_cmd::Phase2bSubcommandError": (
        PRESEAL_REJECTION,
        "phase2b_cmd returns 30 itself post-seal, so one reaching the CLI is pre-seal.",
    ),
    "alive.compose.driver.recover_cmd::RecoverSubcommandError": (
        PRESEAL_REJECTION,
        "recover opens no seal; it consumes immutable terminal/audit artifacts only.",
    ),
    "alive.compose.driver.confirmation::ConfirmationError": (
        PRESEAL_REJECTION,
        "--confirm-seal token or manifest reconstruction rejected before the seal opens.",
    ),
    "alive.compose.driver.identity_lock::AssemblerError": (
        PRESEAL_REJECTION,
        "Execution-identity-lock / worker-digest divergence surfaced before any seal access.",
    ),
    "alive.compose.driver.scientific_runtime::ScientificRuntimeError": (
        PRESEAL_REJECTION,
        "Independent runtime Git/environment identity rejection during carrier assembly.",
    ),
    "alive.compose.driver.bias_report_preseal::ApproximationBiasDeclarationError": (
        PRESEAL_REJECTION,
        "Run-spec approximation_bias_report declaration rejected during carrier assembly.",
    ),
    # ---- config, activation and evidence gates ---------------------------------
    "alive.compose.config2::ScientificModeError": (
        PRESEAL_REJECTION,
        "Owner-authorization gate refusing to start a scientific pipeline.",
    ),
    "alive.compose.config2::Phase2ConfigError": (
        PRESEAL_REJECTION,
        "The externally supplied config is structurally or scientifically invalid.",
    ),
    "alive.compose.activation_evidence::ActivationEvidenceError": (
        PRESEAL_REJECTION,
        "Activation evidence malformed, unbound or overclaiming; reached via config2's gate.",
    ),
    "alive.compose.approximation_bias::ApproximationBiasValidationError": (
        PRESEAL_REJECTION,
        "Approximation-bias / Probe-A evidence judged untrustworthy before any fit.",
    ),
    "alive.compose.datacard::DataCardError": (
        PRESEAL_REJECTION,
        "Data-card declaration invalid or self-contradictory.",
    ),
    # ---- stage-1 inputs, provenance and leakage --------------------------------
    "alive.compose.phase2a::HashMismatchError": (
        PRESEAL_REJECTION,
        "A bound upstream hash disagrees with its expected value; aborts before selection.",
    ),
    "alive.compose.phase2a::InputContractError": (
        PRESEAL_REJECTION,
        "Structural/alignment rejection of the PREPARE-supplied stage-1 artifacts.",
    ),
    "alive.compose.phase2a::ConfigContractError": (
        PRESEAL_REJECTION,
        "Runtime inputs drifted from the preregistered config.",
    ),
    "alive.compose.freeze::FreezeError": (
        PRESEAL_REJECTION,
        "Frozen-bundle construction/validation failure, before the seal.",
    ),
    "alive.compose.freeze::OutcomeLeakageError": (
        PRESEAL_REJECTION,
        "Highest-severity leakage guard; must reach the operator under its own name.",
    ),
    "alive.compose.gates::LeakageError": (
        PRESEAL_REJECTION,
        "Measurability gate refusing a sealed role; not even a ValueError, so needs its own entry.",
    ),
    "alive.compose.fit_role::FitRoleArtifactError": (
        PRESEAL_REJECTION,
        "Fit-role artifact identity/leakage/validation failure.",
    ),
    "alive.compose.provenance2::ProvenanceError": (
        PRESEAL_REJECTION,
        "Self-described PRE-ACCESS abort: a provenance mismatch detectable before access.",
    ),
    "alive.provenance::LedgerError": (
        PRESEAL_REJECTION,
        "A requested run-ledger artifact name is absent when the driver reads it back.",
    ),
    "alive.compose.terminal::TerminalError": (
        PRESEAL_REJECTION,
        "Illegal terminal transition or lock refusal, reachable from recover / run-dir validation.",
    ),
    # ---- estimation and selection ----------------------------------------------
    "alive.compose.select::SelectionError": (
        PRESEAL_REJECTION,
        "OOF selection invalidated before any seal access; carries per-candidate reasons.",
    ),
    "alive.compose.select::OOFFoldManifestError": (
        PRESEAL_REJECTION,
        "Invalid, inconsistent or tampered OOF fold manifest.",
    ),
    "alive.compose.identify::SingularDesignError": (
        PRESEAL_REJECTION,
        "The estimator refuses an estimate; phase2a's full fit runs outside select's handler.",
    ),
    # ---- deep baselines and workers --------------------------------------------
    "alive.compose.baselines_combo::BaselineUnavailable": (
        PRESEAL_REJECTION,
        "A GEARS/CPA worker exited non-zero -- the likeliest real pod failure.",
    ),
    "alive.compose.baseline_subprocess::PayloadError": (
        PRESEAL_REJECTION,
        "Malformed worker payload or prediction file.",
    ),
    "alive.compose.worker_bundle::WorkerBundleError": (
        PRESEAL_REJECTION,
        "Worker-bundle construction or validation failed closed.",
    ),
    # ---- development seed variability (phase2a CONTINUE path) -------------------
    "alive.compose.seed_variability::SeedVariabilityPreflightError": (
        PRESEAL_REJECTION,
        "Self-described pre-access seed-variability binding/verification failure.",
    ),
    "alive.compose.seed_variability::SeedVariabilityContractError": (
        PRESEAL_REJECTION,
        "D2 contract/provenance violation on the development seed sweep, before the seal.",
    ),
    "alive.compose.seed_variability::SeedVariabilityReportError": (
        PRESEAL_REJECTION,
        "Invalid, non-finite or tampered development seed-variability report.",
    ),
    "alive.compose.seed_variability::FoldJobError": (
        PRESEAL_REJECTION,
        "Fold-job alignment, artifact or leakage-proof violation on development roles.",
    ),
    "alive.compose.seed_variability::FoldExecutionError": (
        PRESEAL_REJECTION,
        "A development fold job could not be executed to a verified result.",
    ),
    "alive.compose.seed_variability::SeedAssemblyError": (
        PRESEAL_REJECTION,
        "A seed's covered-order OOF reassembly was not exactly-once.",
    ),
    # ---- phase2b orchestration (outside the seal boundary) ---------------------
    "alive.compose.phase2b::Phase2bError": (
        PRESEAL_REJECTION,
        "Self-described orchestration precondition failure OUTSIDE the seal boundary.",
    ),
    "alive.compose.phase2b::ApproximationBiasReportError": (
        PRESEAL_REJECTION,
        "Phase2bError subclass: the pinned bias report failed fail-closed loading.",
    ),
    "alive.compose.outcome_store::ComposeSealingError": (
        PRESEAL_REJECTION,
        "The sealed-read guard refusing access; the seal is not consumed by a refusal.",
    ),
    "alive.compose.preflight::PreflightError": (
        PRESEAL_REJECTION,
        "The pre-seal gate rejecting the frozen bundle or ledger cross-checks.",
    ),
    # ---- post-seal: handled inside phase2b_cmd, converted to exit 30 -----------
    "alive.compose.durable::DurableLedgerError": (
        POSTSEAL,
        "Durable finalize runs after the seal opens; phase2b_cmd returns 30 rather than raising.",
    ),
    "alive.compose.inference2::ComposeInferenceError": (
        POSTSEAL,
        "simultaneous_theta_bounds runs on sealed outcomes inside the phase2b dispatch.",
    ),
    "alive.compose.metric2::MetricError": (
        POSTSEAL,
        "Sealed-evaluation metric input rejection (invalidate-run policy) inside the dispatch.",
    ),
    "alive.compose.scoring2::ComposeScoringError": (
        POSTSEAL,
        "score_regime runs on sealed outcomes inside the phase2b dispatch.",
    ),
    "alive.compose.verdict2::ComposeVerdictError": (
        POSTSEAL,
        "sealed_verdict runs after the seal is consumed.",
    ),
    "alive.eval.bootstrap::BootstrapError": (
        POSTSEAL,
        "Bootstrap primitive used by sealed inference, after the seal opens.",
    ),
    # ---- bugs: internal invariants, not operator-facing input rejections -------
    "alive.compose.terminal::NoTerminalWritten": (
        BUG,
        "Control-flow sentinel for a protected block that exited without writing a terminal.",
    ),
    "alive.provenance::DuplicateArtifactError": (
        BUG,
        "One raise site: the same ledger artifact name registered twice in one process.",
    ),
    # ---- importable from the driver, but no driver code path raises them -------
    "alive.metrics.distance::DistanceError": (
        UNREACHABLE_FROM_DRIVER,
        "Energy-distance primitive pulled in via alive.metrics' __init__; unused by COMPOSE.",
    ),
    "alive.metrics.selective::MetricError": (
        UNREACHABLE_FROM_DRIVER,
        "Selective-prediction metrics belong to the TG-K562 protocol, not COMPOSE.",
    ),
    # ---- outside the driver's static import graph ------------------------------
    "alive.base.predictor::BaseModelError": (
        UNREACHABLE_FROM_DRIVER,
        "Shared base-predictor API; COMPOSE models raise their own typed errors.",
    ),
    "alive.cli::CliError": (UNREACHABLE_FROM_DRIVER, "The alive CLI, a different entry point."),
    "alive.compose.config::ConfigError": (UNREACHABLE_FROM_DRIVER, "Superseded Phase-1 config."),
    "alive.compose.gears_probe_a::ProbeAEvidenceError": (
        UNREACHABLE_FROM_DRIVER,
        "Probe-A evidence tooling, run from scripts on the pod.",
    ),
    "alive.compose.gene_universe::GeneUniverseError": (
        UNREACHABLE_FROM_DRIVER,
        "Outcome-free roster generator, a PREPARE-stage script.",
    ),
    "alive.compose.kernel_isolation_ci::KernelIsolationCIError": (
        UNREACHABLE_FROM_DRIVER,
        "CI receipt/archive validation tooling.",
    ),
    "alive.compose.network_isolation::NetworkIsolationError": (
        UNREACHABLE_FROM_DRIVER,
        "Seccomp launcher, a separate process the driver never imports.",
    ),
    "alive.compose.verifier_image::VerifierImageLockError": (
        UNREACHABLE_FROM_DRIVER,
        "Verifier OCI image lock tooling.",
    ),
    "alive.compose.worker_identity::WorkerIdentityError": (
        UNREACHABLE_FROM_DRIVER,
        "Worker-side identity attestation, raised inside the worker subprocess.",
    ),
    "alive.config::ConfigError": (UNREACHABLE_FROM_DRIVER, "Repository-wide config loader."),
    "alive.conformal.error_bound::ConformalError": (
        UNREACHABLE_FROM_DRIVER,
        "TG-K562 conformal machinery.",
    ),
    "alive.data.features::FeatureError": (UNREACHABLE_FROM_DRIVER, "Feature builder (PREPARE)."),
    "alive.data.manifest::ManifestError": (UNREACHABLE_FROM_DRIVER, "Split manifest builder."),
    "alive.data.outcome_store::SealingError": (
        UNREACHABLE_FROM_DRIVER,
        "The TG-K562 outcome store; COMPOSE uses compose.outcome_store.",
    ),
    "alive.data.preprocess::PreprocessError": (UNREACHABLE_FROM_DRIVER, "Preprocessing (PREPARE)."),
    "alive.data.replogle::SchemaError": (
        UNREACHABLE_FROM_DRIVER,
        "Replogle CRISPRi loader; a different protocol's dataset.",
    ),
    "alive.eval.diagnostics::DiagnosticsError": (UNREACHABLE_FROM_DRIVER, "TG-K562 diagnostics."),
    "alive.eval.report::ReportError": (
        UNREACHABLE_FROM_DRIVER,
        "TG-K562 reporting layer; COMPOSE reports go through phase2b and durable.",
    ),
    "alive.experiment.develop::DevelopError": (
        UNREACHABLE_FROM_DRIVER,
        "TG-K562 development loop.",
    ),
    "alive.gate.recoverability::GateError": (
        UNREACHABLE_FROM_DRIVER,
        "TG-K562 trust-gate machinery; a different, already-sealed protocol.",
    ),
}


# --------------------------------------------------------------------------- #
# static discovery
# --------------------------------------------------------------------------- #


def _module_path(module: str) -> Path | None:
    flat = _SRC / (module.replace(".", "/") + ".py")
    if flat.is_file():
        return flat
    pkg = _SRC / module.replace(".", "/") / "__init__.py"
    return pkg if pkg.is_file() else None


def _with_parents(module: str) -> set[str]:
    """Importing ``a.b.c`` executes ``a`` and ``a.b``'s ``__init__`` first."""
    parts = module.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def _imported_alive_modules(path: Path) -> set[str]:
    """Every ``alive.*`` module this file imports, at ANY nesting depth.

    Walking the whole AST (not just module-level statements) is required: a
    runtime ``sys.modules`` probe misses ``config2``'s function-local import of
    ``activation_evidence``, which would then be misclassified as unreachable.
    The ``_LAZY_EXPORTS`` branch covers ``alive/compose/__init__.py``'s PEP-562
    lazy-import gate.
    """
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("alive"))
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or not node.module.startswith("alive"):
                continue
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "_LAZY_EXPORTS" for t in node.targets):
                found.update(
                    v.value
                    for v in ast.walk(node.value)
                    if isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                    and v.value.startswith("alive")
                )
    return found


def _static_import_graph(root: str) -> set[str]:
    seen: set[str] = set()
    stack = list(_with_parents(root))
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        path = _module_path(module)
        if path is None:  # a `from pkg import name` where name is not a module
            continue
        seen.add(module)
        for target in _imported_alive_modules(path):
            stack.extend(_with_parents(target))
    return seen


def _exception_classes() -> dict[str, str]:
    """``module::ClassName -> module``, for every exception class under ``src/alive``."""
    pending: list[tuple[str, str, list[str]]] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = str(path.relative_to(_SRC)).removesuffix(".py").replace("/", ".")
        module = module.removesuffix(".__init__")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            bases += [b.attr for b in node.bases if isinstance(b, ast.Attribute)]
            pending.append((module, node.name, bases))
    known = set(_BUILTIN_BASES)
    changed = True
    while changed:  # transitive: SubError(ProjectError(ValueError)) counts too
        changed = False
        for _module, name, bases in pending:
            if name not in known and any(base in known for base in bases):
                known.add(name)
                changed = True
    return {
        f"{module}::{name}": module
        for module, name, _bases in pending
        if name in known and name not in _BUILTIN_BASES
    }


_GRAPH = _static_import_graph(_ROOT_MODULE)
_CLASSES = _exception_classes()


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #


def test_every_exception_class_under_src_is_classified():
    """Fail closed on a NEW exception class -- classify it, do not delete this."""
    unclassified = sorted(set(_CLASSES) - set(_CLASSIFICATION))
    assert not unclassified, (
        "these exception classes have no entry in _CLASSIFICATION:\n  "
        + "\n  ".join(unclassified)
        + "\n\nAdd each one with a classification "
        f"({'/'.join(sorted(_VALID_CLASSIFICATIONS))}) and a one-line justification. "
        "If it is a PRESEAL_REJECTION reachable from the driver, also add it to "
        "cli._KNOWN_PRESEAL_REJECTIONS -- do not delete this check."
    )


def test_the_classification_table_has_no_stale_entries():
    """A renamed or deleted class must not leave a justification behind."""
    stale = sorted(set(_CLASSIFICATION) - set(_CLASSES))
    listed = "\n  ".join(stale)
    assert not stale, f"these _CLASSIFICATION entries name no class under src/alive:\n  {listed}"


def test_every_classification_uses_the_registered_vocabulary():
    bad = {
        key: value[0]
        for key, value in _CLASSIFICATION.items()
        if value[0] not in _VALID_CLASSIFICATIONS
    }
    assert not bad, f"unregistered classifications: {bad}"


def test_every_classification_carries_a_justification():
    missing = sorted(key for key, (_c, why) in _CLASSIFICATION.items() if len(why.strip()) < 20)
    assert not missing, f"these entries need a real one-line justification: {missing}"


def test_the_static_import_graph_is_a_superset_of_a_real_driver_import():
    """The screen must never under-approximate what importing the CLI really pulls.

    Measured in a FRESH interpreter, deliberately not this one. ``sys.modules`` is
    process-global, so under the full suite it also holds everything every other
    test module has imported -- comparing against it would fail on
    ``alive.data.replogle`` and thirty other modules that have nothing to do with
    the driver, and would pass only when this file runs alone.
    """
    probe = (
        "import alive.compose.driver.cli, sys\n"
        "print('\\n'.join(sorted(\n"
        "    name for name, module in sys.modules.items()\n"
        "    if name.startswith('alive') and getattr(module, '__file__', None)\n"
        ")))\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO,
    )
    runtime = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    assert runtime, "the probe imported nothing; the measurement, not the graph, is broken"
    missed = sorted(runtime - _GRAPH)
    assert not missed, (
        "the static import graph missed modules a real import loads: "
        f"{missed}. Widen _imported_alive_modules rather than trusting the screen."
    )


def test_modules_outside_the_driver_graph_are_classified_unreachable():
    """One direction only: outside the graph implies unreachable.

    The converse does not hold -- a class can be importable and still raised by no
    driver code path (``alive.metrics``' primitives arrive through a package
    ``__init__``), so an in-graph ``UNREACHABLE_FROM_DRIVER`` is allowed and rests
    on its justification.
    """
    wrong = sorted(
        key
        for key, module in _CLASSES.items()
        if module not in _GRAPH and _CLASSIFICATION[key][0] != UNREACHABLE_FROM_DRIVER
    )
    assert not wrong, (
        "these classes are outside the driver's static import graph but are not "
        f"classified {UNREACHABLE_FROM_DRIVER}: {wrong}"
    )


def _roster_key(exc_type: type[BaseException]) -> str:
    return f"{exc_type.__module__}::{exc_type.__qualname__}"


def test_the_roster_admits_no_builtin_base():
    """The registered admission rule: typed project classes only.

    ``src/alive/compose`` alone raises a bare ``ValueError`` in over two hundred
    places, most of them internal-invariant violations. Admitting the builtin
    would report those as documented pre-seal rejections.
    """
    builtins_in_roster = [
        exc.__name__
        for exc in cli._KNOWN_PRESEAL_REJECTIONS
        if not exc.__module__.startswith("alive")
    ]
    assert not builtins_in_roster, (
        f"builtin bases in _KNOWN_PRESEAL_REJECTIONS: {builtins_in_roster}. "
        "Give the raise sites a typed class instead."
    )


def test_every_roster_entry_is_classified_preseal():
    misfiled = {
        _roster_key(exc): _CLASSIFICATION.get(_roster_key(exc), ("<unclassified>", ""))[0]
        for exc in cli._KNOWN_PRESEAL_REJECTIONS
        if _CLASSIFICATION.get(_roster_key(exc), ("<unclassified>", ""))[0] != PRESEAL_REJECTION
    }
    assert not misfiled, f"roster entries not classified {PRESEAL_REJECTION}: {misfiled}"


def test_every_preseal_classification_is_covered_by_the_roster():
    """A PRESEAL_REJECTION must actually map to exit 10 -- itself or via a base."""
    rostered = tuple(cli._KNOWN_PRESEAL_REJECTIONS)
    uncovered: list[str] = []
    for key, (classification, _why) in sorted(_CLASSIFICATION.items()):
        if classification != PRESEAL_REJECTION:
            continue
        module_name, _, class_name = key.partition("::")
        module = __import__(module_name, fromlist=[class_name])
        exc_type = getattr(module, class_name)
        if not any(issubclass(exc_type, admitted) for admitted in rostered):
            uncovered.append(key)
    assert not uncovered, (
        "these classes are classified PRESEAL_REJECTION but no roster entry catches "
        f"them, so they exit 1 instead of the contracted 10: {uncovered}"
    )


@pytest.mark.parametrize(
    "name",
    ["SUCCESS_EXIT", "PRESEAL_REJECT_EXIT", "FUTILITY_EXIT", "POSTSEAL_NONCOMPLETE_EXIT"],
)
def test_the_registered_exit_codes_are_unchanged(name):
    expected = {
        "SUCCESS_EXIT": 0,
        "PRESEAL_REJECT_EXIT": 10,
        "FUTILITY_EXIT": 20,
        "POSTSEAL_NONCOMPLETE_EXIT": 30,
    }
    assert getattr(cli, name) == expected[name]
