"""S3 + CloudFront SPA, Cognito Identity Pool, API Lambdas for the web dashboard."""

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigw_integrations,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from constructs import Construct

_INFRA_DIR = Path(__file__).resolve().parent.parent
_WEB_DIST = _INFRA_DIR.parent / "web" / "dist"


def _thing_shadow_iam_resources(iot_arn: str, thing_name: str, shadow_name: str) -> list[str]:
    """IAM ARNs for GetThingShadow / UpdateThingShadow (classic + named shadow)."""
    resources = ["%s:thing/%s" % (iot_arn, thing_name)]
    if shadow_name:
        # Named shadow: arn:...:thing/<thing>/<shadowName> (not .../shadow/<name>)
        resources.append("%s:thing/%s/%s" % (iot_arn, thing_name, shadow_name))
    return resources


class ParkingLotWebStack(Stack):
  def __init__(
      self,
      scope: Construct,
      construct_id: str,
      *,
      iot_data_endpoint: str,
      events_table: dynamodb.ITable,
      thing_name: str,
      shadow_name: str,
      lot_id: str = "lot_1",
      **kwargs,
  ) -> None:
    super().__init__(scope, construct_id, **kwargs)

    region = Stack.of(self).region
    account = Stack.of(self).account
    iot_arn = "arn:aws:iot:%s:%s" % (region, account)

    # --- S3 + CloudFront (SPA hosting) ---
    spa_bucket = s3.Bucket(
        self,
        "SpaBucket",
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        removal_policy=RemovalPolicy.DESTROY,
        auto_delete_objects=True,
        enforce_ssl=True,
    )

    distribution = cloudfront.Distribution(
        self,
        "SpaDistribution",
        default_behavior=cloudfront.BehaviorOptions(
            origin=origins.S3BucketOrigin.with_origin_access_control(spa_bucket),
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        ),
        default_root_object="index.html",
        error_responses=[
            cloudfront.ErrorResponse(
                http_status=403,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=Duration.seconds(0),
            ),
            cloudfront.ErrorResponse(
                http_status=404,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=Duration.seconds(0),
            ),
        ],
    )

    web_url = "https://%s" % distribution.distribution_domain_name

    # --- Cognito Identity Pool (unauthenticated, read-only IoT) ---
    identity_pool = cognito.CfnIdentityPool(
        self,
        "WebIdentityPool",
        allow_unauthenticated_identities=True,
    )

    unauth_role = iam.Role(
        self,
        "WebUnauthRole",
        assumed_by=iam.FederatedPrincipal(
            "cognito-identity.amazonaws.com",
            {
                "StringEquals": {
                    "cognito-identity.amazonaws.com:aud": identity_pool.ref,
                },
                "ForAnyValue:StringLike": {
                    "cognito-identity.amazonaws.com:amr": "unauthenticated",
                },
            },
            "sts:AssumeRoleWithWebIdentity",
        ),
    )
    unauth_role.add_to_policy(
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["iot:Connect"],
            resources=["%s:client/parkinglot_web_*" % iot_arn],
        )
    )
    lot_prefix = "parkinglot/%s" % lot_id
    unauth_role.add_to_policy(
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["iot:Subscribe"],
            resources=[
                "%s:topicfilter/parkinglot/#" % iot_arn,
                "%s:topicfilter/%s/status" % (iot_arn, lot_prefix),
                "%s:topicfilter/%s/summary" % (iot_arn, lot_prefix),
                "%s:topicfilter/parkinglot/+/status" % iot_arn,
                "%s:topicfilter/parkinglot/+/summary" % iot_arn,
            ],
        )
    )
    unauth_role.add_to_policy(
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["iot:Receive"],
            resources=[
                "%s:topic/parkinglot/#" % iot_arn,
                "%s:topic/%s/status" % (iot_arn, lot_prefix),
                "%s:topic/%s/summary" % (iot_arn, lot_prefix),
                "%s:topic/parkinglot/+/status" % iot_arn,
                "%s:topic/parkinglot/+/summary" % iot_arn,
            ],
        )
    )

    cognito.CfnIdentityPoolRoleAttachment(
        self,
        "WebIdentityPoolRoles",
        identity_pool_id=identity_pool.ref,
        roles={"unauthenticated": unauth_role.role_arn},
    )

    # --- API Lambdas ---
    get_snapshot_fn = lambda_.Function(
        self,
        "GetSnapshotFunction",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="handler.handler",
        code=lambda_.Code.from_asset(str(_INFRA_DIR / "lambdas" / "get_snapshot")),
        timeout=Duration.seconds(15),
        environment={
            "THING_NAME": thing_name,
            "SHADOW_NAME": shadow_name,
            "IOT_DATA_ENDPOINT": iot_data_endpoint,
            "TABLE_NAME": events_table.table_name,
            "LOT_ID": lot_id,
            "DEVICE_ID": thing_name,
        },
    )
    get_snapshot_fn.add_to_role_policy(
        iam.PolicyStatement(
            actions=["iot:GetThingShadow"],
            resources=_thing_shadow_iam_resources(iot_arn, thing_name, shadow_name),
        )
    )
    events_table.grant_read_data(get_snapshot_fn)

    get_history_fn = lambda_.Function(
        self,
        "GetHistoryFunction",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="handler.handler",
        code=lambda_.Code.from_asset(str(_INFRA_DIR / "lambdas" / "get_history")),
        timeout=Duration.seconds(15),
        environment={
            "TABLE_NAME": events_table.table_name,
            "DEFAULT_LOT_ID": lot_id,
        },
    )
    events_table.grant_read_data(get_history_fn)

    control_fn = lambda_.Function(
        self,
        "ControlFunction",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="handler.handler",
        code=lambda_.Code.from_asset(str(_INFRA_DIR / "lambdas" / "control")),
        timeout=Duration.seconds(15),
        environment={
            "THING_NAME": thing_name,
            "SHADOW_NAME": shadow_name,
            "IOT_DATA_ENDPOINT": iot_data_endpoint,
            "LOT_ID": lot_id,
            "CONTROL_DEVICE_ID": "web_control",
        },
    )
    control_fn.add_to_role_policy(
        iam.PolicyStatement(
            actions=["iot:Publish"],
            resources=["%s:topic/parkinglot/%s/status" % (iot_arn, lot_id)],
        )
    )
    control_fn.add_to_role_policy(
        iam.PolicyStatement(
            actions=["iot:UpdateThingShadow"],
            resources=_thing_shadow_iam_resources(iot_arn, thing_name, shadow_name),
        )
    )

    # --- HTTP API ---
    http_api = apigwv2.HttpApi(
        self,
        "WebHttpApi",
        cors_preflight=apigwv2.CorsPreflightOptions(
            allow_origins=[web_url, "http://localhost:5173"],
            allow_methods=[
                apigwv2.CorsHttpMethod.GET,
                apigwv2.CorsHttpMethod.POST,
            ],
            allow_headers=["*"],
        ),
    )
    http_api.add_routes(
        path="/snapshot",
        methods=[apigwv2.HttpMethod.GET],
        integration=apigw_integrations.HttpLambdaIntegration(
            "SnapshotIntegration",
            get_snapshot_fn,
        ),
    )
    http_api.add_routes(
        path="/history",
        methods=[apigwv2.HttpMethod.GET],
        integration=apigw_integrations.HttpLambdaIntegration(
            "HistoryIntegration",
            get_history_fn,
        ),
    )
    http_api.add_routes(
        path="/control",
        methods=[apigwv2.HttpMethod.POST],
        integration=apigw_integrations.HttpLambdaIntegration(
            "ControlIntegration",
            control_fn,
        ),
    )

    api_url = http_api.api_endpoint

    # --- Deploy SPA + runtime config (requires web/dist from npm run build) ---
    # Use a single BucketDeployment: a second deployment with prune=True (default)
    # would delete every object not in its source (e.g. index.html after config-only).
    if _WEB_DIST.is_dir():
        s3deploy.BucketDeployment(
            self,
            "DeploySpa",
            sources=[
                s3deploy.Source.asset(str(_WEB_DIST)),
                s3deploy.Source.json_data(
                    "config.json",
                    {
                        "region": region,
                        "iotEndpoint": iot_data_endpoint,
                        "identityPoolId": identity_pool.ref,
                        "apiUrl": api_url,
                        "lotId": lot_id,
                        "thingName": thing_name,
                        "shadowName": shadow_name,
                    },
                ),
            ],
            destination_bucket=spa_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )
    else:
        # Placeholder so the stack deploys before the first frontend build.
        s3deploy.BucketDeployment(
            self,
            "DeployPlaceholder",
            sources=[
                s3deploy.Source.data(
                    "index.html",
                    "<!DOCTYPE html><html><body>"
                    "<h1>Parking Lot Dashboard</h1>"
                    "<p>Run <code>cd web && npm install && npm run build</code> "
                    "then redeploy ParkingLotWebStack.</p></body></html>",
                )
            ],
            destination_bucket=spa_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

    # --- Outputs ---
    CfnOutput(self, "WebUrl", value=web_url)
    CfnOutput(self, "ApiUrl", value=api_url)
    CfnOutput(self, "IdentityPoolId", value=identity_pool.ref)
    CfnOutput(self, "SpaBucketName", value=spa_bucket.bucket_name)
    CfnOutput(self, "DistributionId", value=distribution.distribution_id)
