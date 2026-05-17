export interface AwsCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken: string;
}

function cognitoUrl(region: string): string {
  return `https://cognito-identity.${region}.amazonaws.com/`;
}

async function cognitoPost(
  region: string,
  target: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = await fetch(cognitoUrl(region), {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": target,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Cognito ${target} failed (${response.status}): ${text}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export async function getCognitoCredentials(
  identityPoolId: string,
  region: string,
): Promise<AwsCredentials> {
  const idResponse = await cognitoPost(region, "AWSCognitoIdentityService.GetId", {
    IdentityPoolId: identityPoolId,
  });
  const identityId = idResponse.IdentityId as string;

  const credsResponse = await cognitoPost(
    region,
    "AWSCognitoIdentityService.GetCredentialsForIdentity",
    { IdentityId: identityId },
  );
  const creds = credsResponse.Credentials as {
    AccessKeyId: string;
    SecretKey: string;
    SessionToken: string;
  };
  return {
    accessKeyId: creds.AccessKeyId,
    secretAccessKey: creds.SecretKey,
    sessionToken: creds.SessionToken,
  };
}
