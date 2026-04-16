# My Transport

Mobile-first web app for logging daily transport jobs with notes, image attachments, and monthly PDF export.

## Features

- Log trip date, origin, destination, and notes
- Attach multiple images per trip
- Filter trips by month
- Export monthly summary as PDF
- Dark premium UI tuned for phones first

## Local Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open `http://127.0.0.1:5000`

## Deploy

```bash
vercel deploy -y
```

## Storage Note

This starter uses local SQLite and local file uploads. It works well locally and in preview/demo deployments, but Vercel serverless storage is not persistent by default. For long-term production data, move trips to a managed database and images to object storage.
