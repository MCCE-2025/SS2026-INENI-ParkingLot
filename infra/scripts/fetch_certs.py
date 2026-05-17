#!/usr/bin/env python3
"""Fetch device certificates from a deployed ParkingLotStack.

Reads CloudFormation stack outputs, pulls the certificate bundle from
Secrets Manager, downloads the Amazon Root CA, and prints example CLI
commands for main.py / simulator.py.
"""

import argparse
import json
import os
import sys
import urllib.request

AMAZON_ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"


def _get_stack_outputs(cfn_client, stack_name):
    response = cfn_client.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if not stacks:
        raise SystemExit("Stack %r not found." % stack_name)
    outputs = stacks[0].get("Outputs", [])
    return {item["OutputKey"]: item["OutputValue"] for item in outputs}


def _fetch_secret(secrets_client, secret_arn):
    response = secrets_client.get_secret_value(SecretId=secret_arn)
    return json.loads(response["SecretString"])


def _download_root_ca(url, dest_path):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read()
    with open(dest_path, "wb") as handle:
        handle.write(data)


def main():
    parser = argparse.ArgumentParser(
        description="Materialize IoT device certs from a deployed CDK stack."
    )
    parser.add_argument(
        "--stack",
        default="ParkingLotStack",
        help="CloudFormation stack name (default: ParkingLotStack).",
    )
    parser.add_argument(
        "--output",
        default="../certs",
        help="Directory to write cert files (default: ../certs).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: from environment / AWS config).",
    )
    args = parser.parse_args()

    try:
        import boto3
    except ImportError:
        raise SystemExit(
            "boto3 is required. From infra/, run: uv sync --all-groups"
        ) from None

    session_kwargs = {}
    if args.region:
        session_kwargs["region_name"] = args.region

    session = boto3.Session(**session_kwargs)
    cfn = session.client("cloudformation")
    secrets = session.client("secretsmanager")

    outputs = _get_stack_outputs(cfn, args.stack)
    secret_arn = outputs.get("CertificateSecretArn")
    endpoint = outputs.get("IoTDataEndpoint")
    thing_name = outputs.get("ThingName")
    root_ca_url = outputs.get("AmazonRootCaUrl", AMAZON_ROOT_CA_URL)

    if not secret_arn:
        raise SystemExit(
            "Stack output CertificateSecretArn not found. "
            "Has the stack been deployed?"
        )

    payload = _fetch_secret(secrets, secret_arn)
    cert_pem = payload.get("certificatePem")
    private_key = payload.get("privateKey")
    if not cert_pem or not private_key:
        raise SystemExit(
            "Secret does not contain certificatePem and privateKey fields."
        )

    output_dir = os.path.abspath(args.output)
    os.makedirs(output_dir, exist_ok=True)

    cert_path = os.path.join(output_dir, "device.pem.crt")
    key_path = os.path.join(output_dir, "private.pem.key")
    ca_path = os.path.join(output_dir, "AmazonRootCA1.pem")

    with open(cert_path, "w", encoding="utf-8") as handle:
        handle.write(cert_pem)
        if not cert_pem.endswith("\n"):
            handle.write("\n")

    with open(key_path, "w", encoding="utf-8") as handle:
        handle.write(private_key)
        if not private_key.endswith("\n"):
            handle.write("\n")

    _download_root_ca(root_ca_url, ca_path)

    print("Wrote certificate files to %s" % output_dir)
    print("  %s" % cert_path)
    print("  %s" % key_path)
    print("  %s" % ca_path)
    print()

    if endpoint and thing_name:
        rel_cert = os.path.relpath(cert_path, os.getcwd())
        rel_key = os.path.relpath(key_path, os.getcwd())
        rel_ca = os.path.relpath(ca_path, os.getcwd())
        print("Example (from parking_lot/):")
        print(
            "python main.py --video 0 --data data/coordinates_webcam.yml \\\n"
            "  --iot-endpoint %s \\\n"
            "  --iot-client-id %s \\\n"
            "  --iot-cert %s \\\n"
            "  --iot-key %s \\\n"
            "  --iot-ca %s"
            % (endpoint, thing_name, rel_cert, rel_key, rel_ca)
        )
        print()
        print("Simulator smoke test:")
        print(
            "python simulator.py --spots 8 --interval 3 --max-events 5 \\\n"
            "  --iot-endpoint %s \\\n"
            "  --iot-client-id %s \\\n"
            "  --iot-cert %s \\\n"
            "  --iot-key %s \\\n"
            "  --iot-ca %s"
            % (endpoint, thing_name, rel_cert, rel_key, rel_ca)
        )


if __name__ == "__main__":
    main()
