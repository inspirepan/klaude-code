# Vertex AI setup guide

This guide covers how to configure the CLI to use Vertex AI instead of a Gemini API key.

## When to use Vertex AI
- Enterprise/organization environments with GCP billing
- IAM-based access control and audit logging
- Service account authentication (CI/CD, headless environments)
- GCP-native integration (VPC, private endpoints)

For personal use or quick experimentation, a Gemini API key (`GEMINI_API_KEY`) is simpler.

## Required environment variables

All three must be set:

| Variable | Description | Example |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key file | `/path/to/sa-key.json` |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID | `my-project-123456` |
| `GOOGLE_CLOUD_LOCATION` | GCP region for Vertex AI | `us-central1` |

## What these look like

### GOOGLE_APPLICATION_CREDENTIALS
A file path pointing to a service account JSON key file. The file looks like:
```json
{
  "type": "service_account",
  "project_id": "my-project-123456",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n",
  "client_email": "my-sa@my-project-123456.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/my-sa%40my-project-123456.iam.gserviceaccount.com"
}
```

### GOOGLE_CLOUD_PROJECT
Your GCP project ID (not the display name). Find it in the GCP Console dashboard or run:
```bash
gcloud config get-value project
```

### GOOGLE_CLOUD_LOCATION
The Vertex AI region. Common options:
- `us-central1` (most features, recommended default)
- `europe-west4`
- `asia-northeast1`

## Setup steps

### 1. Enable the Vertex AI API
```bash
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
```

### 2. Create a service account (if you don't have one)
```bash
gcloud iam service-accounts create gemini-image-gen \
  --display-name="Gemini Image Generation" \
  --project=YOUR_PROJECT_ID
```

### 3. Grant the required IAM role
The service account needs the `Vertex AI User` role:
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:gemini-image-gen@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### 4. Create and download a key file
```bash
gcloud iam service-accounts keys create sa-key.json \
  --iam-account=gemini-image-gen@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 5. Set environment variables
Add to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):
```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/sa-key.json"
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
```

## Verification
```bash
uv run scripts/gemini_image_gen.py generate \
  --prompt "A simple test image of a red circle" \
  --out /tmp/vertex-test.png
```
The CLI should print `Auth: Vertex AI detected (project=..., location=...)` to stderr.

## Troubleshooting

### "Permission denied" or 403 errors
- Verify the service account has `roles/aiplatform.user` on the project.
- Check the key file path is correct and readable.

### "API not enabled" errors
- Run `gcloud services enable aiplatform.googleapis.com`.

### Priority: API key takes precedence
If both `GEMINI_API_KEY` and Vertex AI variables are set, the CLI uses the API key. Unset `GEMINI_API_KEY` to force Vertex AI mode.
