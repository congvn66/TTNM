# Cloudflare R2 setup

## Purpose

Cloudflare R2 is the durable object store for immutable original PDFs and the
derived extraction artifacts (OCR text, table structure, evidence and bounding
boxes). PostgreSQL/Supabase remains the source of truth for metadata, revision
history and answer provenance. `runtime/uploads` and `runtime/extracted` are a
disposable local processing cache, not the durable source when R2 is enabled.

## 1. Create the bucket

In Cloudflare Dashboard, open **Storage & databases > R2 > Overview** and create
one private bucket named `sourcelens-documents`. Choose the account/location
required by the project. Do not enable public access for this bucket.

## 2. Create a scoped S3 API token

In the same R2 overview, choose **Manage** next to API Tokens, then create an
Account API token with:

- Permission: `Object Read & Write`.
- Scope: only the `sourcelens-documents` bucket.
- Expiration: a short rotation period for demo environments, or an explicitly
  managed longer expiry for a deployed service.

Save the Access Key ID and Secret Access Key immediately. Cloudflare shows the
secret only once. They must never be committed, put in frontend code or sent to
the browser.

## 3. Configure the backend environment

Copy `.env.example` to `.env`, retain the existing Supabase `DATABASE_URL`, and
set the following values:

```env
STORAGE_BACKEND=r2
R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_BUCKET=sourcelens-documents
R2_ACCESS_KEY_ID=<R2_ACCESS_KEY_ID>
R2_SECRET_ACCESS_KEY=<R2_SECRET_ACCESS_KEY>
R2_REGION=auto
```

`R2_ENDPOINT` is the S3 endpoint displayed after creating the R2 API token.
Use the jurisdiction-specific endpoint supplied by Cloudflare if the bucket was
created with a jurisdiction.

The runtime config reads process environment variables. Load `.env` into the
PowerShell session before starting Python:

```powershell
Set-Location 'C:\Users\Admin\Desktop\TTNM'

$r2Lines = Get-Content .env
foreach ($line in $r2Lines) {
  if ($line -match '^([A-Z0-9_]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
  }
}
```

## 4. Install and verify

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[postgres,object-storage]"
$env:PYTHONPATH = "$PWD\services\backend\src"
& .\.venv\Scripts\python.exe scripts\check_r2.py
```

Expected result contains `backend: r2`, `status: ok`, and the configured bucket
name. The check calls `HeadBucket`; it does not upload, list, or expose files.

## Runtime behavior

```text
upload PDF -> validate/hash/cache locally -> R2 documents/<uuid>.pdf
  -> PostgreSQL document_versions.storage_key
  -> extraction worker reads local cache or downloads R2 object
  -> extraction artifact -> R2 extractions/<version>.json
  -> PostgreSQL regions/evidence/revision graph
```

If R2 is unavailable, an upload fails with `OBJECT_STORAGE_UNAVAILABLE`; the
server does not silently treat a local cache as durable storage. Existing R2
objects are immutable per document version. The API streams a PDF through the
authenticated backend and does not expose a public R2 URL.

## Operational notes

- Keep the bucket private. Use backend streaming or future short-lived signed
  URLs only after owner/authorization checks.
- Configure a lifecycle/backup policy in Cloudflare before real user uploads.
- Removing a local `runtime/` directory only clears cache; it does not delete
  R2 objects or Supabase metadata.
- Do not run MinIO for this runtime. The Docker Compose file now covers only
  optional local PostgreSQL.

## Start the API

The repository script loads `.env` only into its own process and does not print
secret values:

```powershell
.\scripts\start_backend.ps1 -Reload
