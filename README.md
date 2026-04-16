# My Transport

Mobile-first web app for logging daily transport jobs with notes, image attachments, and monthly PDF export.

## Features

- Log trip date, origin, destination, and notes
- Attach multiple images per trip
- Filter trips by month
- Export monthly summary as PDF
- Dark premium UI tuned for phones first
- Supports Supabase Postgres via `DATABASE_URL` or `SUPABASE_DB_URL`
- Supports Supabase Storage for trip photo uploads when server keys are configured

## Local Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
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

When either database URL is present, the app will use Supabase Postgres. When `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are also present, trip photos are uploaded to Supabase Storage bucket `trip-images`.

## Deploy

```bash
vercel deploy -y
```

For Vercel, add `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` in the project environment variables before the next deploy.

## Storage Note

If the Supabase Storage server keys are missing, the app falls back to local filesystem uploads. On Vercel, that fallback is not persistent, so production should always set the Supabase Storage variables.
