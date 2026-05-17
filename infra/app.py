#!/usr/bin/env python3
import aws_cdk as cdk

from parking_lot_cdk.parking_lot_stack import ParkingLotStack
from parking_lot_cdk.parking_lot_web_stack import ParkingLotWebStack

app = cdk.App()
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
