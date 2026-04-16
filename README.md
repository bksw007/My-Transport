# My Transport

Mobile-first web app for logging daily transport jobs with notes, image attachments, and monthly PDF export.

## Features

- Log trip date, origin, destination, and notes
- Attach multiple images per trip
- Filter trips by month
- Export monthly summary as PDF
- Dark premium UI tuned for phones first
- Supports Supabase Postgres via `DATABASE_URL` or `SUPABASE_DB_URL`

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
3. Set one of these environment variables before starting the app:

```bash
export DATABASE_URL="postgresql://..."
```

or

```bash
export SUPABASE_DB_URL="postgresql://..."
```

When either variable is present, the app will use Supabase Postgres and auto-create the `trips` and `trip_images` tables on startup.

## Deploy

```bash
vercel deploy -y
```

For Vercel, add `DATABASE_URL` in the project environment variables before the next deploy.

## Storage Note

Trip data can now live in Supabase Postgres, but image uploads are still stored on the local filesystem in this version. On Vercel, filesystem uploads are not persistent, so the next upgrade should move images into Supabase Storage.
