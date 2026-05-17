"""AWS IoT Core + DynamoDB stack for the parking-lot detector."""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_iot as iot,
    aws_secretsmanager as secretsmanager,
    custom_resources as cr,
)
from constructs import Construct


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

        # --- Device certificate (AwsCustomResource; no L2 for key generation) ---
        create_cert = cr.AwsCustomResource(
            self,
            "CreateDeviceCertificate",
            on_create=cr.AwsSdkCall(
                service="Iot",
                action="createKeysAndCertificate",
                parameters={"setAsActive": True},
                physical_resource_id=cr.PhysicalResourceId.from_response(
                    "certificateId"
                ),
            ),
            on_delete=cr.AwsSdkCall(
                service="Iot",
                action="updateCertificate",
                parameters={
                    "certificateId": cr.PhysicalResourceIdReference(),
                    "newStatus": "INACTIVE",
                },
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE,
            ),
        )
        certificate_arn = create_cert.get_response_field("certificateArn")

        # --- Secrets Manager (L2) + populate via custom resource ---
        device_secret = secretsmanager.Secret(
            self,
            "DeviceCertificateSecret",
            description="X.509 certificate and private key for %s" % thing_name,
            removal_policy=RemovalPolicy.DESTROY,
        )

        populate_secret = cr.AwsCustomResource(
            self,
            "PopulateDeviceCertificateSecret",
            on_create=cr.AwsSdkCall(
                service="SecretsManager",
                action="putSecretValue",
                parameters={
                    "SecretId": device_secret.secret_arn,
                    "SecretString": Stack.of(self).to_json_string(
                        {
                            "certificatePem": create_cert.get_response_field(
                                "certificatePem"
                            ),
                            "privateKey": create_cert.get_response_field(
                                "keyPair.PrivateKey"
                            ),
                        }
                    ),
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "PopulateDeviceCertificateSecret"
                ),
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=[device_secret.secret_arn],
            ),
        )
        populate_secret.node.add_dependency(create_cert)
        populate_secret.node.add_dependency(device_secret)

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
                    "SELECT *, topic(2) as lot_id, spot_id, occupied, ts "
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

        # --- Outputs ---
        CfnOutput(self, "IoTDataEndpoint", value=describe_endpoint.get_response_field("endpointAddress"))
        CfnOutput(self, "ThingName", value=thing.thing_name)
        CfnOutput(self, "CertificateArn", value=certificate_arn)
        CfnOutput(self, "CertificateSecretArn", value=device_secret.secret_arn)
        CfnOutput(self, "CertificateSecretName", value=device_secret.secret_name)
        CfnOutput(self, "EventsTableName", value=events_table.table_name)
        CfnOutput(self, "AmazonRootCaUrl", value=amazon_root_ca_url)
