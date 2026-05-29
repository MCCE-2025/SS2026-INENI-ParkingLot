"""Route 53 hosted zone + ACM certificate (us-east-1) for the web dashboard domain."""

from aws_cdk import CfnOutput, Fn, Stack, aws_certificatemanager as acm, aws_route53 as route53
from constructs import Construct


class ParkingLotDnsStack(Stack):
    """Public hosted zone and CloudFront-compatible TLS certificate."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.domain_name = domain_name

        self.zone = route53.PublicHostedZone(
            self,
            "WebZone",
            zone_name=domain_name,
        )

        self.certificate = acm.Certificate(
            self,
            "WebCertificate",
            domain_name=domain_name,
            validation=acm.CertificateValidation.from_dns(self.zone),
        )

        CfnOutput(
            self,
            "HostedZoneId",
            value=self.zone.hosted_zone_id,
        )
        CfnOutput(
            self,
            "NameServers",
            value=Fn.join(", ", self.zone.hosted_zone_name_servers),
            description=(
                "Create NS records for %s at the parent zone (werschlan.at) "
                "before the certificate can validate."
            ) % domain_name,
        )
        CfnOutput(
            self,
            "CertificateArn",
            value=self.certificate.certificate_arn,
        )
