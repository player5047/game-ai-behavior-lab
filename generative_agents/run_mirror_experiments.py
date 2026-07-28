"""Run the three FYP magic-mirror conditions.

This wrapper runs start.py for:
  A: --mirror none
  B: --mirror division
  C: --mirror unity

It can run one or more base names. Pass A, B, or C to run just one
condition across all bases.
"""

import argparse
import subprocess
import sys
from pathlib import Path


CONDITIONS = [
    ("A", "none"),
    ("B", "division"),
    ("C", "unity"),
]


def build_command(python_exe, script_path, name, args, mirror_mode):
    command = [
        python_exe,
        str(script_path),
        "--name",
        name,
        "--start",
        args.start,
        "--step",
        str(args.step),
        "--stride",
        str(args.stride),
        "--mirror",
        mirror_mode,
        "--verbose",
        args.verbose,
    ]
    if args.log:
        command.extend(["--log", args.log])
    return command


def format_command(command):
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def build_planned_runs(base, suffix_separator):
    return [
        (f"{base}{suffix_separator}{condition}", mirror_mode)
        for condition, mirror_mode in CONDITIONS
    ]


def build_condition_runs(base, suffix_separator, condition):
    mirror_mode = dict(CONDITIONS)[condition]
    return [(f"{base}{suffix_separator}{condition}", mirror_mode)]


def print_run(name, mirror_mode, command):
    print("\n" + "=" * 72)
    print(f"Running {name} with --mirror {mirror_mode}")
    print("Command:")
    print(format_command(command))
    print("=" * 72)


def run_sequential(planned_runs, args, python_exe, start_script, script_dir, checkpoints_root):
    for name, mirror_mode in planned_runs:
        checkpoint_folder = checkpoints_root / name
        if checkpoint_folder.exists() and args.skip_existing:
            print(f"[skip] {name} already exists.")
            continue

        command = build_command(python_exe, start_script, name, args, mirror_mode)
        print_run(name, mirror_mode, command)

        if args.dry_run:
            continue

        result = subprocess.run(command, cwd=script_dir)
        if result.returncode != 0:
            print(f"\n[failed] {name} exited with code {result.returncode}.")
            return result.returncode

    return 0


def run_parallel(planned_runs, args, python_exe, start_script, script_dir, checkpoints_root):
    processes = []
    for name, mirror_mode in planned_runs:
        checkpoint_folder = checkpoints_root / name
        if checkpoint_folder.exists() and args.skip_existing:
            print(f"[skip] {name} already exists.")
            continue

        command = build_command(python_exe, start_script, name, args, mirror_mode)
        print_run(name, mirror_mode, command)

        if args.dry_run:
            continue

        processes.append((name, subprocess.Popen(command, cwd=script_dir)))

    failed = []
    for name, process in processes:
        returncode = process.wait()
        if returncode != 0:
            failed.append((name, returncode))

    if failed:
        print("\nSome runs failed:")
        for name, returncode in failed:
            print(f"  - {name}: exit code {returncode}")
        return failed[0][1]

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run no-mirror, division-mirror, and unity-mirror experiments."
    )
    parser.add_argument("--base", type=str, default="test0.7", help="Base run name")
    parser.add_argument(
        "--bases",
        nargs="+",
        default=None,
        help="One or more base run names. Example: --bases test5.0 test5.1",
    )
    parser.add_argument(
        "--suffix-separator",
        type=str,
        default="",
        help="Text between the base name and A/B/C. Use '_' for names like test5.0_A.",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="20250213-09:30",
        help="Simulation start time passed to start.py",
    )
    parser.add_argument("--step", type=int, default=700, help="Step count per run")
    parser.add_argument("--stride", type=int, default=10, help="Stride minutes")
    parser.add_argument(
        "--verbose", type=str, default="debug", help="Verbose level passed to start.py"
    )
    parser.add_argument(
        "--log",
        type=str,
        default="",
        help="Optional log filename inside each checkpoint folder",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip a condition if its checkpoint folder already exists",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run A/B/C for each base at the same time, then continue to the next base.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them",
    )
    parser.add_argument(
        "condition",
        nargs="?",
        choices=[condition for condition, _ in CONDITIONS],
        help="Optional condition to run: A=none, B=division, C=unity",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    start_script = script_dir / "start.py"
    checkpoints_root = script_dir / "results" / "checkpoints"
    python_exe = sys.executable

    bases = args.bases or [args.base]
    if args.condition:
        planned_by_base = [
            (base, build_condition_runs(base, args.suffix_separator, args.condition))
            for base in bases
        ]
    else:
        planned_by_base = [
            (base, build_planned_runs(base, args.suffix_separator))
            for base in bases
        ]

    existing = [
        name
        for _, planned_runs in planned_by_base
        for name, _ in planned_runs
        if (checkpoints_root / name).exists()
    ]
    if existing and not args.skip_existing:
        print("These checkpoint folders already exist:")
        for name in existing:
            print(f"  - {checkpoints_root / name}")
        print("\nChoose a new --base, delete/archive those folders, or use --skip-existing.")
        return 1

    for base, planned_runs in planned_by_base:
        print("\n" + "#" * 72)
        print(f"Batch {base}: starting {len(planned_runs)} mirror conditions")
        print("#" * 72)

        if args.parallel:
            returncode = run_parallel(
                planned_runs, args, python_exe, start_script, script_dir, checkpoints_root
            )
        else:
            returncode = run_sequential(
                planned_runs, args, python_exe, start_script, script_dir, checkpoints_root
            )

        if returncode != 0:
            print(f"\n[stopped] Batch {base} did not finish cleanly.")
            return returncode

    print("\nAll requested mirror experiments finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
