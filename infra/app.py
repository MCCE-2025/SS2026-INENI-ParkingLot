#!/usr/bin/env python3
import os

import aws_cdk as cdk

from parking_lot_cdk.parking_lot_dns_stack import ParkingLotDnsStack
from parking_lot_cdk.parking_lot_stack import ParkingLotStack
from parking_lot_cdk.parking_lot_web_stack import ParkingLotWebStack

app = cdk.App()
web_domain_name = app.node.try_get_context("web_domain_name")

if web_domain_name:
    env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    )
    env_us_east_1 = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="us-east-1",
    )

    device_stack = ParkingLotStack(app, "ParkingLotStack", env=env)

    dns_stack = ParkingLotDnsStack(
        app,
        "ParkingLotDnsStack",
        domain_name=web_domain_name,
        env=env_us_east_1,
        cross_region_references=True,
    )

    web_stack = ParkingLotWebStack(
        app,
        "ParkingLotWebStack",
        env=env,
        cross_region_references=True,
        iot_data_endpoint=device_stack.iot_data_endpoint,
        events_table=device_stack.events_table,
        thing_name=device_stack.thing_name_value,
        shadow_name=device_stack.shadow_name_value,
        lot_id=device_stack.lot_id_value,
        domain_name=web_domain_name,
        certificate_arn=dns_stack.certificate.certificate_arn,
        hosted_zone_id=dns_stack.zone.hosted_zone_id,
    )
    web_stack.add_dependency(dns_stack)
else:
    device_stack = ParkingLotStack(app, "ParkingLotStack")
    ParkingLotWebStack(
        app,
        "ParkingLotWebStack",
        iot_data_endpoint=device_stack.iot_data_endpoint,
        events_table=device_stack.events_table,
        thing_name=device_stack.thing_name_value,
        shadow_name=device_stack.shadow_name_value,
        lot_id=device_stack.lot_id_value,
    )

app.synth()
