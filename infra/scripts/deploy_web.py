#!/usr/bin/env python3
"""Build the web SPA and deploy ParkingLotDnsStack + ParkingLotWebStack."""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-dns",
        action="store_true",
        help="Skip ParkingLotDnsStack (use after subdomain NS delegation is in place)",
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

    deploy_cmd = ["npx", "aws-cdk", "deploy", "--require-approval", "never"]
    if args.skip_dns:
        deploy_cmd.append("ParkingLotWebStack")
    else:
        deploy_cmd.extend(["ParkingLotDnsStack", "ParkingLotWebStack"])

    print("==> cdk deploy %s" % " ".join(deploy_cmd[3:]))
    subprocess.run(deploy_cmd, cwd=infra_dir, check=True)


if __name__ == "__main__":
    main()
