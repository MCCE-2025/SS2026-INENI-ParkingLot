#!/usr/bin/env python3
import aws_cdk as cdk

from parking_lot_cdk.parking_lot_stack import ParkingLotStack

app = cdk.App()
ParkingLotStack(app, "ParkingLotStack")
app.synth()
