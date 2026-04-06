# Bedrock Setup

Klaude supports AWS Bedrock through the `bedrock` protocol, but Bedrock is not configured as a built-in provider.

Configure it in `~/.klaude/klaude-config.yaml` as a custom provider.

## Required Fields

- `provider_name`: local provider alias
- `protocol: bedrock`
- `aws_region`: Bedrock runtime region
- one authentication method: `aws_profile`
- or one authentication method: `aws_access_key` + `aws_secret_key`
- `model_list[].model_name`
- `model_list[].model_id`

`aws_session_token` is optional when using temporary credentials.

## What `model_id` Can Be

`model_id` can be any Bedrock identifier accepted by the Anthropic Bedrock SDK:

- foundation model ID
- inference profile ID
- inference profile ARN

Examples:

- `anthropic.claude-sonnet-4-5-20250929-v1:0`
- `global.anthropic.claude-sonnet-4-5-20250929-v1:0`
- `arn:aws:bedrock:us-east-1:123456789012:inference-profile/global.anthropic.claude-sonnet-4-5-20250929-v1:0`

## Example With `aws_profile`

```yaml
provider_list:
- provider_name: bedrock-prod
  protocol: bedrock
  aws_profile: my-profile
  aws_region: us-east-1
  model_list:
  - model_name: claude-sonnet-4-5
    model_id: global.anthropic.claude-sonnet-4-5-20250929-v1:0
    context_limit: 200000

main_model: claude-sonnet-4-5@bedrock-prod
```

## Example With Access Keys

```yaml
provider_list:
- provider_name: bedrock-prod
  protocol: bedrock
  aws_access_key: ${AWS_ACCESS_KEY_ID}
  aws_secret_key: ${AWS_SECRET_ACCESS_KEY}
  aws_region: ${AWS_REGION}
  model_list:
  - model_name: claude-sonnet-4-5
    model_id: arn:aws:bedrock:us-east-1:123456789012:inference-profile/global.anthropic.claude-sonnet-4-5-20250929-v1:0
    context_limit: 200000

main_model: claude-sonnet-4-5@bedrock-prod
```

## Notes

- Do not set `api_key` for Bedrock.
- You normally do not need `base_url`; the client derives the endpoint from `aws_region`.
- Authentication uses AWS SigV4 signing, not Bearer tokens.
- Model selection still uses `model@provider`, for example `claude-sonnet-4-5@bedrock-prod`.
- If you store access keys directly in `~/.klaude/klaude-config.yaml`, keep that file out of source control.