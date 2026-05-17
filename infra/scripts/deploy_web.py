#!/usr/bin/env python3
"""Build the web SPA and deploy ParkingLotWebStack."""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stack",
        default="ParkingLotWebStack",
        help="CDK stack name to deploy (default: ParkingLotWebStack)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    web_dir = repo_root / "web"
    infra_dir = repo_root / "infra"

    print("==> npm install (web/)")
    subprocess.run(["npm", "install"], cwd=web_dir, check=True)

    print("==> npm run build (web/)")
    subprocess.run(["npm", "run", "build"], cwd=web_dir, check=True)

    if not (web_dir / "dist").is_dir():
        print("error: web/dist not found after build", file=sys.stderr)
        sys.exit(1)

    print("==> cdk deploy %s" % args.stack)
    subprocess.run(
        ["uv", "run", "cdk", "deploy", args.stack, "--require-approval", "never"],
        cwd=infra_dir,
        check=True,
    )


if __name__ == "__main__":
    main()
