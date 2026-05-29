"""AWS IoT Core + DynamoDB stack for the parking-lot detector."""

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_iot as iot,
    aws_lambda as lambda_,
    aws_secretsmanager as secretsmanager,
    custom_resources as cr,
)
from constructs import Construct


# Inline Lambda that provisions an IoT device certificate and stores the
# cert + private key as a JSON blob in Secrets Manager. Doing cert creation
# AND secret population inside a single Lambda avoids the
# `AwsCustomResource` JSON-templating bug where PEM newlines from
# `createKeysAndCertificate` get interpolated as raw control characters
# into the custom resource Lambda's `Parameters` string, producing
# "Bad control character in string literal in JSON at position 248".
_CERTIFICATE_PROVISIONER_CODE = '''
import json
import time
import boto3

iot = boto3.client("iot")
secrets = boto3.client("secretsmanager")


def _looks_like_cert_id(value):
    return isinstance(value, str) and len(value) >= 32 and all(
        c in "0123456789abcdef" for c in value.lower()
    )


def on_event(event, context):
    request_type = event["RequestType"]
    props = event.get("ResourceProperties", {}) or {}
    secret_id = props.get("SecretId")

    if request_type == "Create":
        cert = iot.create_keys_and_certificate(setAsActive=True)
        payload = json.dumps(
            {
                "certificatePem": cert["certificatePem"],
                "privateKey": cert["keyPair"]["PrivateKey"],
            }
        )
        secrets.put_secret_value(SecretId=secret_id, SecretString=payload)
        return {
            "PhysicalResourceId": cert["certificateId"],
            "Data": {
                "CertificateArn": cert["certificateArn"],
                "CertificateId": cert["certificateId"],
            },
        }

    if request_type == "Update":
        cert_id = event["PhysicalResourceId"]
        described = iot.describe_certificate(certificateId=cert_id)
        return {
            "PhysicalResourceId": cert_id,
            "Data": {
                "CertificateArn": described["certificateDescription"][
                    "certificateArn"
                ],
                "CertificateId": cert_id,
            },
        }

    if request_type == "Delete":
        cert_id = event.get("PhysicalResourceId")
        if not _looks_like_cert_id(cert_id):
            return {"PhysicalResourceId": cert_id or "missing"}

        try:
            iot.update_certificate(certificateId=cert_id, newStatus="INACTIVE")
        except iot.exceptions.ResourceNotFoundException:
            return {"PhysicalResourceId": cert_id}

        # Attachments are deleted by CloudFormation first, but the IoT
        # control plane is eventually consistent; retry the delete a few
        # times to ride out lingering principal attachments.
        for _ in range(6):
            try:
                iot.delete_certificate(certificateId=cert_id)
                break
            except iot.exceptions.ResourceNotFoundException:
                break
            except iot.exceptions.DeleteConflictException:
                time.sleep(5)

        return {"PhysicalResourceId": cert_id}

    return {"PhysicalResourceId": event.get("PhysicalResourceId", "noop")}
'''


class ParkingLotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        thing_name = self.node.try_get_context("thing_name") or "parking_lot_camera_01"
        shadow_name = self.node.try_get_context("shadow_name") or "occupancy"
        events_table_name = (
            self.node.try_get_context("events_table_name") or "ParkingLotEvents"
        )
        policy_name = "%s-policy" % thing_name

        region = Stack.of(self).region
        account = Stack.of(self).account
        iot_arn = "arn:aws:iot:%s:%s" % (region, account)

        # --- IoT Thing (L1) ---
        thing = iot.CfnThing(self, "Thing", thing_name=thing_name)

        # --- Secrets Manager (L2) — placeholder, populated by provisioner ---
        device_secret = secretsmanager.Secret(
            self,
            "DeviceCertificateSecret",
            description="X.509 certificate and private key for %s" % thing_name,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Device certificate + secret population (single Lambda) ---
        provisioner_fn = lambda_.Function(
            self,
            "CertificateProvisionerFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.on_event",
            code=lambda_.Code.from_inline(_CERTIFICATE_PROVISIONER_CODE),
            timeout=Duration.seconds(120),
            description=(
                "Creates an IoT device certificate and stores the cert + "
                "private key as JSON in Secrets Manager."
            ),
        )
        provisioner_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iot:CreateKeysAndCertificate"],
                resources=["*"],
            )
        )
        provisioner_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "iot:UpdateCertificate",
                    "iot:DeleteCertificate",
                    "iot:DescribeCertificate",
                ],
                resources=["%s:cert/*" % iot_arn],
            )
        )
        device_secret.grant_write(provisioner_fn)

        certificate_provider = cr.Provider(
            self,
            "CertificateProvider",
            on_event_handler=provisioner_fn,
        )

        provision_cert = CustomResource(
            self,
            "CertificateProvisioner",
            service_token=certificate_provider.service_token,
            properties={"SecretId": device_secret.secret_arn},
        )
        provision_cert.node.add_dependency(device_secret)

        certificate_arn = provision_cert.get_att_string("CertificateArn")

        # --- IoT policy document (L2 iam) -> L1 CfnPolicy ---
        shadow_topic = (
            "$aws/things/%s/shadow/name/%s" % (thing_name, shadow_name)
        )
        policy_document = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["iot:Connect"],
                    resources=["%s:client/%s" % (iot_arn, thing_name)],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["iot:Publish"],
                    resources=[
                        "%s:topic/parkinglot/*/status" % iot_arn,
                        "%s:topic/parkinglot/*/summary" % iot_arn,
                    ],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["iot:GetThingShadow", "iot:UpdateThingShadow"],
                    resources=["%s:thing/%s" % (iot_arn, thing_name)],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["iot:Publish", "iot:Subscribe", "iot:Receive"],
                    resources=[
                        "%s:topic/%s/*" % (iot_arn, shadow_topic),
                        "%s:topicfilter/%s/*" % (iot_arn, shadow_topic),
                    ],
                ),
            ]
        )

        iot_policy = iot.CfnPolicy(
            self,
            "DevicePolicy",
            policy_name=policy_name,
            policy_document=policy_document.to_json(),
        )

        iot.CfnPolicyPrincipalAttachment(
            self,
            "PolicyPrincipalAttachment",
            policy_name=iot_policy.policy_name,
            principal=certificate_arn,
        )

        iot.CfnThingPrincipalAttachment(
            self,
            "ThingPrincipalAttachment",
            thing_name=thing.thing_name,
            principal=certificate_arn,
        )

        # --- DynamoDB events table (L2) ---
        events_table = dynamodb.Table(
            self,
            "EventsTable",
            table_name=events_table_name,
            partition_key=dynamodb.Attribute(
                name="lot_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="ts",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # --- IoT rule IAM role (L2) ---
        rule_role = iam.Role(
            self,
            "TopicRuleRole",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
        )
        events_table.grant_write_data(rule_role)

        # --- IoT Topic Rule (L1) ---
        iot.CfnTopicRule(
            self,
            "StatusToDynamoDBRule",
            rule_name="ParkingLotStatusToDynamoDB",
            topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                sql=(
                    "SELECT *, topic(2) as lot_id, spot_id, occupied, ts, epoch "
                    "FROM 'parkinglot/+/status'"
                ),
                aws_iot_sql_version="2016-03-23",
                actions=[
                    iot.CfnTopicRule.ActionProperty(
                        dynamo_d_bv2=iot.CfnTopicRule.DynamoDBv2ActionProperty(
                            role_arn=rule_role.role_arn,
                            put_item=iot.CfnTopicRule.PutItemInputProperty(
                                table_name=events_table.table_name,
                            ),
                        ),
                    )
                ],
            ),
        )

        # --- IoT data endpoint (AwsCustomResource) ---
        describe_endpoint = cr.AwsCustomResource(
            self,
            "DescribeIotDataEndpoint",
            on_create=cr.AwsSdkCall(
                service="Iot",
                action="describeEndpoint",
                parameters={"endpointType": "iot:Data-ATS"},
                physical_resource_id=cr.PhysicalResourceId.of("IotDataEndpoint"),
            ),
            on_update=cr.AwsSdkCall(
                service="Iot",
                action="describeEndpoint",
                parameters={"endpointType": "iot:Data-ATS"},
                physical_resource_id=cr.PhysicalResourceId.of("IotDataEndpoint"),
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE,
            ),
        )

        amazon_root_ca_url = (
            "https://www.amazontrust.com/repository/AmazonRootCA1.pem"
        )

        # Exposed for ParkingLotWebStack (cross-stack constructor refs).
        self.iot_data_endpoint = describe_endpoint.get_response_field(
            "endpointAddress"
        )
        self.events_table = events_table
        self.thing_name_value = thing_name
        self.shadow_name_value = shadow_name
        self.lot_id_value = self.node.try_get_context("lot_id") or "lot_1"

        # --- Outputs ---
        CfnOutput(self, "IoTDataEndpoint", value=describe_endpoint.get_response_field("endpointAddress"))
        CfnOutput(self, "ThingName", value=thing.thing_name)
        CfnOutput(self, "CertificateArn", value=certificate_arn)
        CfnOutput(self, "CertificateSecretArn", value=device_secret.secret_arn)
        CfnOutput(self, "CertificateSecretName", value=device_secret.secret_name)
        CfnOutput(self, "EventsTableName", value=events_table.table_name)
        CfnOutput(self, "AmazonRootCaUrl", value=amazon_root_ca_url)
