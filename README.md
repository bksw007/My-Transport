# My Transport

Mobile-first web app for logging daily transport jobs with notes, image attachments, and monthly PDF export.

## Features

- Log trip date, origin, destination, and notes
- Attach multiple images per trip
- Filter trips by month
- Export monthly summary as PDF
- Google login gate before accessing the app
- Dark premium UI tuned for phones first
- Requires Supabase Postgres via `DATABASE_URL` or `SUPABASE_DB_URL`
- Supports Supabase Storage for trip photo uploads when server keys are configured

## Local Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
export GOOGLE_CLIENT_ID="your-google-oauth-client-id"
export GOOGLE_CLIENT_SECRET="your-google-oauth-client-secret"
export SUPABASE_URL="https://your-project-ref.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
export SUPABASE_STORAGE_BUCKET="trip-images"
.venv/bin/python app.py
```

Open `http://127.0.0.1:5000`

## Supabase Setup

1. Create a Supabase project
2. Copy the pooled Postgres connection string
3. Copy your project URL and service role key from Supabase
4. Set these environment variables before starting the app:

```bash
export DATABASE_URL="postgresql://..."
export SUPABASE_URL="https://your-project-ref.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
export SUPABASE_STORAGE_BUCKET="trip-images"
```

or

```bash
export SUPABASE_DB_URL="postgresql://..."
export SUPABASE_URL="https://your-project-ref.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
```

The app only uses Supabase/Postgres for database access. If neither `DATABASE_URL` nor `SUPABASE_DB_URL` is set, startup fails instead of falling back to a local database. When `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are also present, trip photos are uploaded to Supabase Storage bucket `trip-images`.

## Google Login Setup

1. Create an OAuth 2.0 Web Client in Google Cloud Console
2. Add this authorized redirect URI for local development:

```text
http://127.0.0.1:5000/auth/google/callback
```

3. Add your deployed callback URL too, for example:

```text
https://your-domain.com/auth/google/callback
```

4. Set these environment variables:

```bash
export GOOGLE_CLIENT_ID="your-google-oauth-client-id"
export GOOGLE_CLIENT_SECRET="your-google-oauth-client-secret"
```

## Deploy

```bash
vercel deploy -y
```

For Vercel, add `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` in the project environment variables before the next deploy.

## Storage Note

If the Supabase Storage server keys are missing, the app falls back to local filesystem uploads. On Vercel, that fallback is not persistent, so production should always set the Supabase Storage variables.
