#!/usr/bin/env python3
"""Assemble a full simulator.py command line from stack outputs and cert paths.

Reads CloudFormation outputs for the IoT data endpoint and Thing name (same
sources as fetch_certs.py), verifies certificate files exist, introspects
simulator.py's argparse definition for flag names, and prints a ready-to-run
command intended to be executed from parking_lot/.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

# Required when simulator runs (build_iot_publisher(..., required=True)).
_IOT_REQUIRED_DESTS = frozenset(
    {"iot_endpoint", "iot_client_id", "iot_cert", "iot_key", "iot_ca"}
)

_CERT_FILES = (
    "device.pem.crt",
    "private.pem.key",
    "AmazonRootCA1.pem",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parking_lot_dir() -> Path:
    return _repo_root() / "parking_lot"


def _import_simulator_parser():
    parking_lot = str(_parking_lot_dir())
    if parking_lot not in sys.path:
        sys.path.insert(0, parking_lot)
    from simulator import build_parser  # noqa: PLC0415

    return build_parser()


def _get_stack_outputs(cfn_client, stack_name: str) -> dict[str, str]:
    response = cfn_client.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if not stacks:
        raise SystemExit("Stack %r not found." % stack_name)
    outputs = stacks[0].get("Outputs", [])
    return {item["OutputKey"]: item["OutputValue"] for item in outputs}


def _action_by_dest(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    by_dest: dict[str, argparse.Action] = {}
    for action in parser._actions:  # noqa: SLF001
        if action.dest and action.dest != "help":
            by_dest[action.dest] = action
    return by_dest


def _option_strings(action: argparse.Action) -> list[str]:
    return [opt for opt in action.option_strings if opt.startswith("--")]


def required_dests_for_simulator() -> frozenset[str]:
    """Dest names that must be set for a working simulator IoT run."""
    return _IOT_REQUIRED_DESTS


def resolve_cert_paths(certs_dir: Path) -> dict[str, Path]:
    """Map iot_cert / iot_key / iot_ca dests to PEM paths; exit if missing."""
    names = {
        "iot_cert": _CERT_FILES[0],
        "iot_key": _CERT_FILES[1],
        "iot_ca": _CERT_FILES[2],
    }
    resolved: dict[str, Path] = {}
    missing_files: list[str] = []
    for dest, filename in names.items():
        path = certs_dir / filename
        if not path.is_file():
            missing_files.append(str(path))
        else:
            resolved[dest] = path.resolve()
    if missing_files:
        raise SystemExit(
            "Certificate file(s) not found:\n  %s\n"
            "Run fetch_certs.py first, e.g.:\n"
            "  uv run python scripts/fetch_certs.py --stack ParkingLotStack "
            "--output ../certs"
            % "\n  ".join(missing_files)
        )
    return resolved


def fetch_iot_values_from_stack(
    stack_name: str,
    region: str | None,
) -> dict[str, str]:
    """Return iot_endpoint and iot_client_id from CloudFormation outputs."""
    try:
        import boto3
    except ImportError:
        raise SystemExit(
            "boto3 is required. From infra/, run: uv sync --all-groups"
        ) from None

    session_kwargs = {}
    if region:
        session_kwargs["region_name"] = region
    session = boto3.Session(**session_kwargs)
    outputs = _get_stack_outputs(session.client("cloudformation"), stack_name)

    endpoint = outputs.get("IoTDataEndpoint")
    thing_name = outputs.get("ThingName")
    missing = []
    if not endpoint:
        missing.append("IoTDataEndpoint")
    if not thing_name:
        missing.append("ThingName")
    if missing:
        raise SystemExit(
            "Stack output(s) missing: %s. Has the stack been deployed?"
            % ", ".join(missing)
        )
    return {"iot_endpoint": endpoint, "iot_client_id": thing_name}


def assemble_simulator_argv(
    values: dict[str, object],
    *,
    include_defaults: bool = False,
    cwd: Path | None = None,
) -> list[str]:
    """Build argv fragments for simulator.py from dest -> value mappings.

    Paths for cert/key/ca are made relative to *cwd* when possible (for
    copy-paste from parking_lot/). Other non-default values are included;
    with *include_defaults*, every defined flag is emitted.
    """
    parser = _import_simulator_parser()
    actions = _action_by_dest(parser)
    argv: list[str] = ["simulator.py"]

    for dest, action in sorted(actions.items(), key=lambda item: item[0]):
        if dest in values:
            value = values[dest]
        elif include_defaults:
            value = action.default
        else:
            continue

        if value is None:
            continue
        if not include_defaults and value == action.default:
            continue

        options = _option_strings(action)
        if not options:
            continue
        flag = options[0]

        if isinstance(value, Path):
            if cwd is not None:
                try:
                    value = os.path.relpath(value, cwd)
                except ValueError:
                    value = str(value)
            else:
                value = str(value)
        elif isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        else:
            value = str(value)

        argv.extend([flag, value])

    return argv


def format_shell_command(
    argv: list[str],
    *,
    use_uv: bool = True,
    multiline: bool = True,
) -> str:
    """Format argv as a shell command (default: multiline with uv run)."""
    if not argv or argv[0] != "simulator.py":
        raise ValueError("argv must start with 'simulator.py'")
    sim_argv = argv[1:]
    prefix = ["uv", "run", "python", "simulator.py"] if use_uv else ["python", "simulator.py"]
    parts = prefix + sim_argv
    if not multiline:
        return " ".join(shlex.quote(part) for part in parts)
    if len(sim_argv) <= 3:
        return " ".join(shlex.quote(part) for part in parts)
    lines = [shlex.quote(prefix[0])]
    for part in prefix[1:3]:
        lines[-1] += " " + shlex.quote(part)
    rest = sim_argv
    chunk_size = 2
    for index in range(0, len(rest), chunk_size):
        chunk = rest[index : index + chunk_size]
        lines.append("  " + " ".join(shlex.quote(part) for part in chunk))
    return " \\\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch IoT stack outputs and certificate paths, then print a "
            "full simulator.py command for parking_lot/."
        )
    )
    parser.add_argument(
        "--stack",
        default="ParkingLotStack",
        help="CloudFormation stack name (default: ParkingLotStack).",
    )
    parser.add_argument(
        "--certs",
        default="../certs",
        help="Directory with device PEM files (default: ../certs from infra/).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: from environment / AWS config).",
    )
    parser.add_argument(
        "--iot-endpoint",
        default=None,
        help="Override IoT data endpoint (default: from stack output).",
    )
    parser.add_argument(
        "--iot-client-id",
        default=None,
        help="Override MQTT client / Thing name (default: from stack).",
    )
    sim = parser.add_argument_group(
        "simulator",
        "Optional simulator flags (defaults match simulator.py).",
    )
    sim.add_argument("--spots", type=int, default=8)
    sim.add_argument("--interval", type=float, default=3.0)
    sim.add_argument("--flip-prob", type=float, default=0.25)
    sim.add_argument("--initial-occupancy-prob", type=float, default=None)
    sim.add_argument("--script", default=None)
    sim.add_argument("--seed", type=int, default=None)
    sim.add_argument("--max-events", type=int, default=5)
    sim.add_argument(
        "--iot-lot-id",
        default=None,
        help="Override --iot-lot-id (default: simulator default lot_1).",
    )
    parser.add_argument(
        "--one-line",
        action="store_true",
        help="Print a single-line command instead of a wrapped multiline one.",
    )
    parser.add_argument(
        "--list-required",
        action="store_true",
        help="Print required dest/flag names from argparse and exit.",
    )
    return parser


def _ensure_importable() -> None:
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Device dependencies missing. Either:\n"
            "  cd %s && uv sync --all-groups   # infra (boto3 + simulator imports)\n"
            "  cd %s && uv sync                 # repo root\n"
            "Then re-run this script."
            % (_repo_root() / "infra", _repo_root())
        ) from None


def main() -> None:
    _ensure_importable()
    args = build_parser().parse_args()

    if args.list_required:
        parser = _import_simulator_parser()
        actions = _action_by_dest(parser)
        required = required_dests_for_simulator()
        print("Required for simulator.py (IoT, via build_iot_publisher required=True):")
        for dest in sorted(required):
            action = actions[dest]
            flags = ", ".join(_option_strings(action)) or dest
            print("  %s  (%s)" % (dest, flags))
        print("\nOptional simulator flags (have defaults in simulator.py):")
        for dest, action in sorted(actions.items()):
            if dest in required:
                continue
            flags = ", ".join(_option_strings(action)) or dest
            default = action.default
            print("  %s  %s  default=%r" % (dest, flags, default))
        return

    certs_dir = Path(args.certs)
    if not certs_dir.is_absolute():
        certs_dir = (Path.cwd() / certs_dir).resolve()
    cert_paths = resolve_cert_paths(certs_dir)

    if args.iot_endpoint and args.iot_client_id:
        iot_values = {
            "iot_endpoint": args.iot_endpoint,
            "iot_client_id": args.iot_client_id,
        }
    else:
        if args.iot_endpoint or args.iot_client_id:
            raise SystemExit(
                "Provide both --iot-endpoint and --iot-client-id to skip "
                "stack lookup, or omit both to read them from the stack."
            )
        iot_values = fetch_iot_values_from_stack(args.stack, args.region)

    values: dict[str, object] = {
        **iot_values,
        **{dest: path for dest, path in cert_paths.items()},
        "spots": args.spots,
        "interval": args.interval,
        "flip_prob": args.flip_prob,
        "max_events": args.max_events,
    }
    if args.initial_occupancy_prob is not None:
        values["initial_occupancy_prob"] = args.initial_occupancy_prob
    if args.script is not None:
        values["script"] = args.script
    if args.seed is not None:
        values["seed"] = args.seed
    if args.iot_lot_id is not None:
        values["iot_lot_id"] = args.iot_lot_id

    parking_lot = _parking_lot_dir()
    argv = assemble_simulator_argv(values, cwd=parking_lot)
    cmd = format_shell_command(argv, multiline=not args.one_line)

    print("# Run from parking_lot/ (after uv sync at repo root):")
    print("cd %s" % parking_lot)
    print(cmd)


if __name__ == "__main__":
    main()
