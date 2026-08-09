"""Run E6 edge acceptance checks and write immutable evidence manifests."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal[2]
Classification = Literal[
    "automated-local", "hardware-required", "customer-data-required", "central-required"
]
Status = Literal["PASS", "FAIL", "SKIP", "NOT_EXECUTED"]

SCHEMA_VERSION: SchemaVersion = 2

CLASS_AUTOMATED_LOCAL: Classification = "automated-local"
CLASS_HARDWARE_REQUIRED: Classification = "hardware-required"
CLASS_CUSTOMER_DATA_REQUIRED: Classification = "customer-data-required"
CLASS_CENTRAL_REQUIRED: Classification = "central-required"
VALID_CLASSIFICATIONS = frozenset(
    {
        CLASS_AUTOMATED_LOCAL,
        CLASS_HARDWARE_REQUIRED,
        CLASS_CUSTOMER_DATA_REQUIRED,
        CLASS_CENTRAL_REQUIRED,
    }
)

PASS: Status = "PASS"  # noqa: S105 - inspection status constant, not a credential
FAIL: Status = "FAIL"
SKIP: Status = "SKIP"
NOT_EXECUTED: Status = "NOT_EXECUTED"

_TIMEOUT_QUALITY = 600.0
_TIMEOUT_PYTEST = 3600.0
_TIMEOUT_PNPM = 1200.0
_TIMEOUT_MKDOCS = 1800.0
_TIMEOUT_COMPOSE = 120.0
_TIMEOUT_DOCKER_BUILD = 1800.0
_TIMEOUT_DOCKER_RUN = 120.0
_TIMEOUT_DOCKER_POLL = 180.0
_ARTIFACT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_REQUIRED_ARTIFACT_NAMES = frozenset(
    {
        "application",
        "product-model",
        "component-model",
        "rule",
        "configuration",
        "acceptance-manifest",
    }
)


class EnvironmentEvidence(BaseModel):
    """Execution environment recorded with each acceptance run."""

    model_config = ConfigDict(extra="forbid")

    git_revision: str
    git_branch: str
    python_version: str
    uv_version: str
    docker_version: str = ""
    pnpm_version: str = ""
    timestamp_utc: datetime
    host_platform: str


class ArtifactLock(BaseModel):
    """Checksums for artifacts locked before any acceptance command runs."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["complete", "incomplete"]
    detail: str
    checksums: dict[str, str] = Field(default_factory=dict)


class ItemEvidence(BaseModel):
    """Typed evidence for one acceptance matrix item."""

    model_config = ConfigDict(extra="forbid")

    id: str
    scenario: str
    classification: Classification
    required_environment: str
    status: Status
    detail: str
    duration_seconds: float
    started_at: datetime
    finished_at: datetime
    executed_assertions: list[str]
    evidence_links: list[str]
    artifact_checksums: dict[str, str]
    depends_on: list[str] = Field(default_factory=list)


class AcceptanceManifest(BaseModel):
    """Versioned machine-readable E6 acceptance evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: SchemaVersion
    label: str
    generated_at: datetime
    environment: EnvironmentEvidence
    artifact_lock: ArtifactLock
    items: list[ItemEvidence]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class RunOptions:
    repo_root: Path
    pytest_enabled: bool
    pnpm_enabled: bool
    docker_enabled: bool
    mkdocs_enabled: bool
    docker_image_check_enabled: bool


@dataclass(frozen=True)
class RunResult:
    status: Status
    detail: str
    duration_seconds: float


@dataclass(frozen=True)
class AcceptanceItem:
    id: str
    scenario: str
    classification: Classification
    required_environment: str
    runner: Callable[[RunOptions], RunResult] | None = None
    pytest_node_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()


def _which(program: str) -> str | None:
    return shutil.which(program)


def run_command(
    argv: Sequence[str], *, cwd: Path | None = None, timeout: float = 300.0
) -> CommandResult:
    """Run argv with no shell and report unavailable commands as results."""
    executable = _which(argv[0])
    if executable is None:
        return CommandResult(127, "", f"command not found: {argv[0]}")
    try:
        completed = subprocess.run(  # noqa: S603 - all command programs are module-defined
            [executable, *argv[1:]],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"command {argv[0]} timed out after {timeout:.0f}s")
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"command {argv[0]} could not start: {exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def aggregate_statuses(statuses: Sequence[Status]) -> Status:
    """Map per-command statuses to one item status: FAIL beats SKIP beats PASS."""
    if FAIL in statuses:
        return FAIL
    if all(status == PASS for status in statuses):
        return PASS
    return SKIP


def _tail(text: str, lines: int = 10) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def run_command_group(
    commands: Sequence[tuple[str, Sequence[str]]], options: RunOptions, timeout: float
) -> RunResult:
    started = time.monotonic()
    details: list[str] = []
    statuses: list[Status] = []
    for name, argv in commands:
        if _which(argv[0]) is None:
            details.append(f"{name}: SKIP (command not found: {argv[0]})")
            statuses.append(SKIP)
            continue
        result = run_command(argv, cwd=options.repo_root, timeout=timeout)
        if result.ok:
            details.append(f"{name}: PASS")
            statuses.append(PASS)
        else:
            details.append(f"{name}: FAIL\n{_tail(result.stderr or result.stdout)}")
            statuses.append(FAIL)
    return RunResult(aggregate_statuses(statuses), "\n".join(details), time.monotonic() - started)


def run_single_command(
    name: str, argv: Sequence[str], options: RunOptions, timeout: float
) -> RunResult:
    started = time.monotonic()
    if _which(argv[0]) is None:
        return RunResult(SKIP, f"{name} skipped: command not found: {argv[0]}", 0.0)
    result = run_command(argv, cwd=options.repo_root, timeout=timeout)
    if result.ok:
        return RunResult(PASS, f"{name} passed", time.monotonic() - started)
    return RunResult(
        FAIL,
        f"{name} failed\n{_tail(result.stderr or result.stdout, 20)}",
        time.monotonic() - started,
    )


def run_python_quality_gates(options: RunOptions) -> RunResult:
    return run_command_group(
        (
            ("ruff check", ["uv", "run", "ruff", "check", "."]),
            ("ruff format", ["uv", "run", "ruff", "format", "--check", "."]),
            ("mypy", ["uv", "run", "mypy", "."]),
        ),
        options,
        _TIMEOUT_QUALITY,
    )


def run_python_test_suite(options: RunOptions) -> RunResult:
    if not options.pytest_enabled:
        return RunResult(SKIP, "skipped: --no-pytest", 0.0)
    return run_single_command("pytest", ["uv", "run", "pytest"], options, _TIMEOUT_PYTEST)


def run_pytest_nodes(item: AcceptanceItem, options: RunOptions) -> RunResult:
    """Run only the explicit regression nodes that assert a matrix behavior."""
    if not options.pytest_enabled:
        return RunResult(SKIP, "skipped: --no-pytest", 0.0)
    return run_single_command(
        "pytest node assertions",
        ["uv", "run", "pytest", *item.pytest_node_ids],
        options,
        _TIMEOUT_PYTEST,
    )


def run_frontend_gates(options: RunOptions) -> RunResult:
    if not options.pnpm_enabled:
        return RunResult(SKIP, "skipped: --no-pnpm", 0.0)
    return run_command_group(
        (
            ("pnpm build", ["pnpm", "-r", "build"]),
            ("pnpm lint", ["pnpm", "-r", "lint"]),
            ("pnpm test", ["pnpm", "-r", "test"]),
        ),
        options,
        _TIMEOUT_PNPM,
    )


def run_docs_build(options: RunOptions) -> RunResult:
    if not options.mkdocs_enabled:
        return RunResult(SKIP, "skipped: --no-mkdocs", 0.0)
    return run_single_command(
        "mkdocs", ["uv", "run", "mkdocs", "build", "--strict"], options, _TIMEOUT_MKDOCS
    )


def run_compose_render(options: RunOptions) -> RunResult:
    if not options.docker_enabled:
        return RunResult(SKIP, "skipped: --no-docker", 0.0)
    return run_single_command(
        "docker compose config",
        ["docker", "compose", "-f", "compose.yaml", "config", "--quiet"],
        options,
        _TIMEOUT_COMPOSE,
    )


def _wait_for_container_health(name: str) -> str:
    deadline = time.monotonic() + _TIMEOUT_DOCKER_POLL
    last_status = "unknown"
    while time.monotonic() < deadline:
        result = run_command(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", name], timeout=30.0
        )
        last_status = result.stdout.strip()
        if last_status in {"healthy", "unhealthy"}:
            return last_status
        if not last_status:
            return "no health status reported by docker"
        time.sleep(5.0)
    return f"not healthy within {int(_TIMEOUT_DOCKER_POLL)}s (last status: {last_status})"


def _docker_cleanup(container: str, image_tag: str) -> None:
    run_command(["docker", "rm", "-f", container], timeout=60.0)
    run_command(["docker", "rmi", "-f", image_tag], timeout=60.0)


def run_edge_image_healthcheck(options: RunOptions) -> RunResult:
    """Build, health-check, restart, and health-check the edge image container."""
    if not options.docker_image_check_enabled:
        return RunResult(SKIP, "skipped: explicit --docker required", 0.0)
    if _which("docker") is None:
        return RunResult(SKIP, "skipped: docker not available", 0.0)
    started = time.monotonic()
    tag = f"assemblyvision-edge-acceptance:{uuid.uuid4().hex[:12]}"
    container = f"edge-acceptance-{uuid.uuid4().hex[:8]}"
    build = run_command(
        ["docker", "build", "-f", "apps/edge-service/Dockerfile", "-t", tag, "."],
        cwd=options.repo_root,
        timeout=_TIMEOUT_DOCKER_BUILD,
    )
    if not build.ok:
        return RunResult(
            FAIL,
            f"edge image build failed\n{_tail(build.stderr or build.stdout, 20)}",
            time.monotonic() - started,
        )
    try:
        start = run_command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                tag,
                "serve",
                "--output",
                "/var/lib/assemblyvision/media",
                "--db",
                "/var/lib/assemblyvision/db/edge.sqlite3",
                "--host",
                "127.0.0.1",
            ],
            cwd=options.repo_root,
            timeout=_TIMEOUT_DOCKER_RUN,
        )
        if not start.ok:
            return RunResult(
                FAIL,
                f"container start failed\n{_tail(start.stderr or start.stdout, 20)}",
                time.monotonic() - started,
            )
        initial_health = _wait_for_container_health(container)
        if initial_health != "healthy":
            return RunResult(
                FAIL,
                f"initial container health status: {initial_health}",
                time.monotonic() - started,
            )
        restart = run_command(["docker", "restart", container], timeout=_TIMEOUT_DOCKER_RUN)
        if not restart.ok:
            return RunResult(
                FAIL,
                f"container restart failed\n{_tail(restart.stderr or restart.stdout, 20)}",
                time.monotonic() - started,
            )
        restarted_health = _wait_for_container_health(container)
        if restarted_health == "healthy":
            return RunResult(
                PASS,
                f"image {tag} built; container healthy before and after restart",
                time.monotonic() - started,
            )
        return RunResult(
            FAIL,
            f"post-restart container health status: {restarted_health}",
            time.monotonic() - started,
        )
    finally:
        _docker_cleanup(container, tag)


def _item(
    item_id: str,
    scenario: str,
    classification: Classification,
    required_environment: str = "",
    *,
    pytest_node: str = "",
    depends_on: tuple[str, ...] = (),
    assertions: tuple[str, ...] = (),
) -> AcceptanceItem:
    nodes = (pytest_node,) if pytest_node else ()
    return AcceptanceItem(
        item_id,
        scenario,
        classification,
        required_environment,
        pytest_node_ids=nodes,
        depends_on=depends_on,
        assertions=assertions or nodes,
    )


ACCEPTANCE_ITEMS: tuple[AcceptanceItem, ...] = (
    AcceptanceItem(
        "AUT-01",
        "python quality gates (ruff, format, mypy)",
        CLASS_AUTOMATED_LOCAL,
        "",
        run_python_quality_gates,
    ),
    AcceptanceItem(
        "AUT-02", "python test suite (pytest)", CLASS_AUTOMATED_LOCAL, "", run_python_test_suite
    ),
    AcceptanceItem(
        "AUT-03",
        "frontend gates (pnpm build, lint, test)",
        CLASS_AUTOMATED_LOCAL,
        "",
        run_frontend_gates,
    ),
    AcceptanceItem(
        "AUT-04", "docs build (mkdocs --strict)", CLASS_AUTOMATED_LOCAL, "", run_docs_build
    ),
    AcceptanceItem(
        "AUT-05", "compose template renders", CLASS_AUTOMATED_LOCAL, "", run_compose_render
    ),
    AcceptanceItem(
        "AUT-06",
        "edge image healthcheck and restart recovery",
        CLASS_AUTOMATED_LOCAL,
        "",
        run_edge_image_healthcheck,
        assertions=("container reaches healthy before and after docker restart",),
    ),
    _item(
        "E6-A1",
        "product type validation",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen customer data for every applicable product type",
    ),
    _item(
        "E6-A2",
        "missing component detection",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen customer NG samples for every required component",
    ),
    _item(
        "E6-A3",
        "missing manual detection",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen customer samples with manual-presence ground truth",
    ),
    _item(
        "E6-A4",
        "barcode failure handling",
        CLASS_HARDWARE_REQUIRED,
        "barcode reader hardware, confirmed barcode standard, and production samples",
    ),
    _item(
        "E6-A5",
        "product-position shift",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen customer captures across the approved position range",
    ),
    _item(
        "E6-A6",
        "normal production variation",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen representative customer production data",
    ),
    _item(
        "E6-A7",
        "consecutive OK products",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen customer production sequence with OK ground truth",
    ),
    _item(
        "E6-A8",
        "consecutive NG products",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen customer production sequence with NG ground truth",
    ),
    _item(
        "E6-A9",
        "mixed product types",
        CLASS_CUSTOMER_DATA_REQUIRED,
        "locked unseen mixed-product customer production sequence",
    ),
    _item(
        "E6-A10",
        "no product handling",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_pipeline.py::test_no_product_is_failsafe_ng",
    ),
    _item(
        "E6-A11",
        "multiple products window integrity",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_product_window.py::TestIdentityContinuity::test_multi_product_frame_aborts_active_window",
    ),
    _item(
        "E6-A12",
        "offline operation",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_upload_scheduler.py::TestLongOutageDrain::test_prolonged_offline_inspection_restart_and_duplicate_free_drain",
    ),
    _item(
        "E6-A13",
        "network outage",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_upload_scheduler.py::TestRetryBehavior::test_network_interruption_schedules_retry",
    ),
    _item(
        "E6-A14",
        "repeated network disconnect (flap)",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_upload_scheduler.py::TestCircuitBreaker::test_retryable_failures_open_circuit_and_stop_attempts",
    ),
    _item(
        "E6-A15",
        "central outage",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_upload_scheduler.py::TestRetryBehavior::test_network_interruption_schedules_retry",
    ),
    _item(
        "E6-A16",
        "duplicate upload idempotency",
        CLASS_CENTRAL_REQUIRED,
        "central server deployment with a frozen Edge-to-central receipt contract",
    ),
    _item(
        "E6-A17",
        "application restart recovery",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_upload_scheduler.py::TestRestartRecovery::test_restart_reclaims_and_drains",
    ),
    _item(
        "E6-A18",
        "power-loss recovery",
        CLASS_HARDWARE_REQUIRED,
        "edge industrial computer and controlled power-cut procedure with authorized site access",
    ),
    _item(
        "E6-A19",
        "disk full and pressure fail-safe",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_retention_config.py::TestRuntimeFailSafe::test_stop_mode_forces_inspection_not_ready",
    ),
    _item(
        "E6-A20",
        "accelerator fault injection",
        CLASS_HARDWARE_REQUIRED,
        "edge inference accelerator, fault-injection procedure, and authorized system access",
    ),
    _item(
        "E6-A21",
        "database failure and corruption",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_storage_integrity.py::TestDatabaseIntegrity::test_corrupt_database_fails_closed",
    ),
    _item(
        "E6-A22",
        "backup and representative restore",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_backup.py::test_backup_restore_round_trip_preserves_pending_evidence",
    ),
    _item(
        "E6-A23",
        "container restart recovery",
        CLASS_AUTOMATED_LOCAL,
        depends_on=("AUT-06",),
        assertions=("container reaches healthy after docker restart",),
    ),
    _item(
        "E6-A24",
        "clock drift correlation",
        CLASS_AUTOMATED_LOCAL,
        "dedicated clock-drift harness is not implemented",
    ),
    _item(
        "E6-A25",
        "checksum failure rejection",
        CLASS_AUTOMATED_LOCAL,
        pytest_node="apps/edge-service/tests/test_storage_integrity.py::TestIntegrityScan::test_checksum_mismatch_is_faulted_when_verified",
    ),
    _item(
        "E6-A26",
        "long-running soak",
        CLASS_HARDWARE_REQUIRED,
        "running edge line with representative workload and customer-agreed soak duration",
    ),
    _item(
        "E6-A27",
        "camera disconnect and recovery",
        CLASS_HARDWARE_REQUIRED,
        "vendor camera SDK, physical camera, and a disconnect/reconnect procedure",
    ),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run E6 edge acceptance items and emit evidence.")
    parser.add_argument("--out", required=True, dest="out_dir", type=Path, help="Output directory")
    parser.add_argument(
        "--label", default="", type=str, help="Optional run label recorded in the manifest"
    )
    parser.add_argument("--no-pytest", action="store_true", help="Skip the python test suite gate")
    parser.add_argument("--no-pnpm", action="store_true", help="Skip the frontend gates")
    parser.add_argument(
        "--no-docker", action="store_true", help="Skip the compose template render gate"
    )
    parser.add_argument("--no-mkdocs", action="store_true", help="Skip the docs build gate")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Opt-in: build, restart, and healthcheck the edge image",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Lock an artifact by SHA-256; repeat for each artifact",
    )
    parser.add_argument(
        "--acceptance-manifest", type=Path, help="Acceptance manifest to lock by SHA-256"
    )
    return parser.parse_args(argv)


def build_options(args: argparse.Namespace, repo_root: Path) -> RunOptions:
    return RunOptions(
        repo_root,
        not args.no_pytest,
        not args.no_pnpm,
        not args.no_docker,
        not args.no_mkdocs,
        args.docker,
    )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a regular artifact file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def parse_artifact_lock(
    specifications: Sequence[str], acceptance_manifest: Path | None
) -> ArtifactLock:
    """Validate artifact specifications and lock their checksums before execution."""
    paths: dict[str, Path] = {}
    for specification in specifications:
        name, separator, path_text = specification.partition("=")
        if not separator or not _ARTIFACT_NAME.fullmatch(name) or not path_text:
            raise ValueError(
                f"invalid artifact specification {specification!r}; expected NAME=PATH"
            )
        if name in paths:
            raise ValueError(f"duplicate artifact name: {name}")
        paths[name] = Path(path_text)
    if acceptance_manifest is not None:
        if "acceptance-manifest" in paths:
            raise ValueError("acceptance-manifest artifact name is reserved")
        paths["acceptance-manifest"] = acceptance_manifest
    checksums: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ValueError(f"artifact does not exist or is not a file: {path}")
        checksums[name] = sha256_file(path)
    missing = sorted(_REQUIRED_ARTIFACT_NAMES - set(paths))
    if missing:
        return ArtifactLock(
            state="incomplete",
            detail=f"missing required artifact lock(s): {', '.join(missing)}",
            checksums=checksums,
        )
    return ArtifactLock(
        state="complete",
        detail="all required candidate artifacts locked before execution",
        checksums=checksums,
    )


def _git_env(repo_root: Path) -> tuple[str, str]:
    revision = run_command(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, timeout=10.0)
    branch = run_command(["git", "branch", "--show-current"], cwd=repo_root, timeout=10.0)
    return (
        revision.stdout.strip() if revision.ok else "",
        branch.stdout.strip() if branch.ok else "",
    )


def _tool_version(argv: Sequence[str]) -> str:
    result = run_command(argv, timeout=10.0)
    lines = result.stdout.strip().splitlines()
    return lines[0] if result.ok and lines else ""


def collect_environment(repo_root: Path) -> EnvironmentEvidence:
    revision, branch = _git_env(repo_root)
    return EnvironmentEvidence(
        git_revision=revision,
        git_branch=branch,
        python_version=platform.python_version(),
        uv_version=_tool_version(["uv", "--version"]),
        docker_version=_tool_version(["docker", "--version"]) if _which("docker") else "",
        pnpm_version=_tool_version(["pnpm", "--version"]) if _which("pnpm") else "",
        timestamp_utc=datetime.now(UTC),
        host_platform=platform.platform(),
    )


def _resolve_runner(item: AcceptanceItem) -> Callable[[RunOptions], RunResult] | None:
    if item.runner is None:
        return None
    module = sys.modules.get(__name__)
    current = getattr(module, item.runner.__name__, None) if module is not None else None
    return cast(Callable[[RunOptions], RunResult], current) if callable(current) else item.runner


def _execute_item(item: AcceptanceItem, options: RunOptions) -> RunResult:
    runner_fn = _resolve_runner(item)
    if runner_fn is not None:
        return runner_fn(options)
    if item.pytest_node_ids:
        return run_pytest_nodes(item, options)
    if item.depends_on:
        return RunResult(SKIP, "resolved from gates", 0.0)
    return RunResult(
        NOT_EXECUTED, f"not executed locally; requires {item.required_environment}", 0.0
    )


def _resolve_dependency_item(
    item: AcceptanceItem, gate_results: Mapping[str, RunResult]
) -> RunResult:
    missing = [dependency for dependency in item.depends_on if dependency not in gate_results]
    if missing:
        return RunResult(
            NOT_EXECUTED, f"dependency gate(s) missing: {', '.join(sorted(missing))}", 0.0
        )
    statuses = [gate_results[dependency].status for dependency in item.depends_on]
    detail = "; ".join(
        f"{dependency}={status}"
        for dependency, status in zip(item.depends_on, statuses, strict=True)
    )
    if FAIL in statuses:
        return RunResult(FAIL, f"required gate failed: {detail}", 0.0)
    if all(status == PASS for status in statuses):
        return RunResult(PASS, f"required gate assertions passed: {detail}", 0.0)
    return RunResult(SKIP, f"required gate was not executed: {detail}", 0.0)


def run_acceptance(
    options: RunOptions,
) -> list[tuple[AcceptanceItem, RunResult, datetime, datetime]]:
    gate_results: dict[str, RunResult] = {}
    results: list[tuple[AcceptanceItem, RunResult, datetime, datetime]] = []
    for item in ACCEPTANCE_ITEMS:
        started = datetime.now(UTC)
        if item.depends_on:
            result = _resolve_dependency_item(item, gate_results)
        else:
            result = _execute_item(item, options)
        finished = datetime.now(UTC)
        results.append((item, result, started, finished))
        if item.runner is not None:
            gate_results[item.id] = result
    return results


def build_manifest(
    *,
    environment: EnvironmentEvidence,
    item_results: Sequence[tuple[AcceptanceItem, RunResult, datetime, datetime]],
    label: str,
    artifact_lock: ArtifactLock,
) -> AcceptanceManifest:
    return AcceptanceManifest(
        schema_version=SCHEMA_VERSION,
        label=label,
        generated_at=environment.timestamp_utc,
        environment=environment,
        artifact_lock=artifact_lock,
        items=[
            ItemEvidence(
                id=item.id,
                scenario=item.scenario,
                classification=item.classification,
                required_environment=item.required_environment,
                status=result.status,
                detail=result.detail,
                duration_seconds=result.duration_seconds,
                started_at=started,
                finished_at=finished,
                executed_assertions=list(item.assertions),
                evidence_links=[],
                artifact_checksums=artifact_lock.checksums,
                depends_on=list(item.depends_on),
            )
            for item, result, started, finished in item_results
        ],
    )


def format_summary(manifest: AcceptanceManifest) -> str:
    lines = [
        "AssemblyVision E6 edge acceptance evidence",
        f"generated_at: {manifest.generated_at.isoformat()}",
        f"label: {manifest.label}",
        f"artifact_lock: {manifest.artifact_lock.state}",
        "",
    ]
    lines.extend(f"{item.id} {item.status} {item.scenario}" for item in manifest.items)
    return "\n".join(lines) + "\n"


def write_atomic(target: Path, content: str) -> None:
    """Write a new file durably without replacing any existing evidence."""
    if target.exists():
        raise FileExistsError(target)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f"{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # link() creates the final path atomically and refuses an existing
        # target, unlike replace() which could erase a concurrent run's proof.
        os.link(tmp_name, target)
        os.unlink(tmp_name)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _exit_code(
    item_results: Sequence[tuple[AcceptanceItem, RunResult, datetime, datetime]],
    artifact_lock: ArtifactLock,
) -> int:
    if any(result.status == FAIL for _, result, _, _ in item_results):
        return 1
    local_incomplete = any(
        item.classification == CLASS_AUTOMATED_LOCAL and result.status in {SKIP, NOT_EXECUTED}
        for item, result, _, _ in item_results
    )
    return 2 if artifact_lock.state == "incomplete" or local_incomplete else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir: Path = args.out_dir
    repo_root = Path(__file__).resolve().parents[1]
    try:
        artifact_lock = parse_artifact_lock(args.artifact, args.acceptance_manifest)
    except ValueError as exc:
        raise SystemExit(f"artifact lock error: {exc}") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    environment = collect_environment(repo_root)
    item_results = run_acceptance(build_options(args, repo_root))
    manifest = build_manifest(
        environment=environment,
        item_results=item_results,
        label=args.label,
        artifact_lock=artifact_lock,
    )
    run_id = f"{environment.timestamp_utc.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}"
    evidence_path = out_dir / f"edge-acceptance-evidence-{run_id}.json"
    summary_path = out_dir / f"edge-acceptance-summary-{run_id}.txt"
    write_atomic(
        evidence_path, json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    write_atomic(summary_path, format_summary(manifest))
    print(f"wrote {evidence_path}")
    print(f"wrote {summary_path}")
    print(format_summary(manifest).rstrip())
    return _exit_code(item_results, artifact_lock)


if __name__ == "__main__":
    raise SystemExit(main())
