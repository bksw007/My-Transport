from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import closing
from datetime import date, datetime
from io import BytesIO
from itertools import zip_longest
from mimetypes import guess_type
from pathlib import Path
from typing import Iterable

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
import psycopg
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from supabase import Client, create_client
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = (
    Path(tempfile.gettempdir()) / "my-transport"
    if os.environ.get("VERCEL")
    else BASE_DIR
)
UPLOAD_DIR = RUNTIME_DIR / "uploads"
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "trip-images")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
VALID_SUGGESTION_FIELDS = {"origin", "destination", "owner"}
PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "my-transport-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


def get_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL or SUPABASE_DB_URL is required")
    return DATABASE_URL


def get_db() -> psycopg.Connection:
    if "db" not in g:
        g.db = psycopg.connect(get_database_url())
    return g.db


def get_storage_client() -> Client | None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    if "storage_client" not in g:
        g.storage_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return g.storage_client


@app.teardown_appcontext
def close_db(_: object | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with closing(psycopg.connect(get_database_url())) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trips (
                    id BIGSERIAL PRIMARY KEY,
                    trip_date DATE NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    owner TEXT DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE trips ADD COLUMN IF NOT EXISTS owner TEXT DEFAULT ''
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_images (
                    id BIGSERIAL PRIMARY KEY,
                    trip_id BIGINT NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
                    file_name TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    storage_path TEXT NOT NULL DEFAULT '',
                    public_url TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trips_trip_date ON trips (trip_date DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trip_images_trip_id ON trip_images (trip_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trip_images_storage_path ON trip_images (storage_path)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS suggestions (
                    id BIGSERIAL PRIMARY KEY,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (field, value)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_suggestions_field ON suggestions (field)
                """
            )
        connection.commit()


def register_pdf_fonts() -> None:
    global PDF_FONT_REGULAR, PDF_FONT_BOLD

    # Sarabun is bundled in the repo and covers Thai + Latin + digits +
    # all tone marks — same font used in the web UI.  System fallbacks
    # are only relevant for a dev box without the bundled files.
    font_candidates = [
        (
            "MyTransportThai",
            BASE_DIR / "assets" / "fonts" / "Sarabun-Regular.ttf",
            BASE_DIR / "assets" / "fonts" / "Sarabun-Bold.ttf",
        ),
        (
            "MyTransportThaiFallback",
            Path("/System/Library/Fonts/Supplemental/Ayuthaya.ttf"),
            Path("/System/Library/Fonts/Supplemental/Ayuthaya.ttf"),
        ),
        (
            "MyTransportThaiFallbackAlt",
            Path("/System/Library/Fonts/Supplemental/Sathu.ttf"),
            Path("/System/Library/Fonts/Supplemental/Sathu.ttf"),
        ),
    ]

    for font_name, regular_path, bold_path in font_candidates:
        if not regular_path.exists() or not bold_path.exists():
            continue
        try:
            regular_name = f"{font_name}-Regular"
            bold_name = f"{font_name}-Bold"
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
            PDF_FONT_REGULAR = regular_name
            PDF_FONT_BOLD = bold_name
            return
        except Exception:
            continue


def is_allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def normalize_month_value(month_value: str | None) -> str:
    fallback = date.today().strftime("%Y-%m")
    if not month_value:
        return fallback

    try:
        return datetime.strptime(month_value, "%Y-%m").strftime("%Y-%m")
    except ValueError:
        try:
            return datetime.strptime(month_value, "%Y-%m-%d").strftime("%Y-%m")
        except ValueError:
            return fallback


def month_bounds(month_value: str | None) -> tuple[str, str]:
    selected_month = normalize_month_value(month_value)
    selected = datetime.strptime(selected_month, "%Y-%m")

    if selected.month == 12:
        next_month = datetime(selected.year + 1, 1, 1)
    else:
        next_month = datetime(selected.year, selected.month + 1, 1)

    return selected.strftime("%Y-%m-%d"), next_month.strftime("%Y-%m-%d")


def fetch_trips(month_value: str | None) -> tuple[list[dict], dict]:
    start, end = month_bounds(month_value)
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                t.id,
                t.trip_date,
                t.origin,
                t.destination,
                t.note,
                t.owner,
                COALESCE(STRING_AGG(i.file_name, '||' ORDER BY i.id), '') AS image_names,
                COALESCE(STRING_AGG(i.original_name, '||' ORDER BY i.id), '') AS original_names,
                COALESCE(STRING_AGG(i.public_url, '||' ORDER BY i.id), '') AS public_urls,
                COALESCE(STRING_AGG(i.id::text, '||' ORDER BY i.id), '') AS image_ids
            FROM trips t
            LEFT JOIN trip_images i ON i.trip_id = t.id
            WHERE t.trip_date >= %s AND t.trip_date < %s
            GROUP BY t.id
            ORDER BY t.trip_date DESC, t.id DESC
            """,
            (start, end),
        )
        rows = cursor.fetchall()

    trips = []
    for row in rows:
        row_id = row[0]
        row_trip_date = row[1]
        row_origin = row[2]
        row_destination = row[3]
        row_note = row[4]
        row_owner = row[5]
        row_image_names = row[6]
        row_original_names = row[7]
        row_public_urls = row[8]
        row_image_ids = row[9]
        trip_date_value = row_trip_date.isoformat() if hasattr(row_trip_date, "isoformat") else str(row_trip_date)
        image_names = row_image_names.split("||") if row_image_names else []
        original_names = row_original_names.split("||") if row_original_names else []
        public_urls = row_public_urls.split("||") if row_public_urls else []
        image_ids = row_image_ids.split("||") if row_image_ids else []
        images = [
            {
                "id": int(image_id) if image_id else None,
                "file_name": file_name,
                "original_name": original_name,
                "url": public_url or url_for("static", filename=f"uploads/{file_name}"),
            }
            for image_id, file_name, original_name, public_url in zip_longest(
                image_ids,
                image_names,
                original_names,
                public_urls,
                fillvalue="",
            )
        ]
        trips.append(
            {
                "id": row_id,
                "trip_date": trip_date_value,
                "origin": row_origin,
                "destination": row_destination,
                "note": row_note,
                "owner": row_owner,
                "images": images,
            }
        )

    summary = {
        "count": len(trips),
        "days": len({trip["trip_date"] for trip in trips}),
        "attachments": sum(len(trip["images"]) for trip in trips),
    }
    return trips, summary


def save_images(files: Iterable) -> list[dict]:
    saved_images: list[dict] = []
    storage_client = get_storage_client()
    for image in files:
        if not image or not image.filename:
            continue
        if not is_allowed_file(image.filename):
            raise ValueError(f"ไฟล์ {image.filename} ไม่รองรับ")

        original_name = secure_filename(image.filename)
        suffix = Path(original_name).suffix.lower()
        generated_name = f"{uuid.uuid4().hex}{suffix}"
        content_type = image.mimetype or guess_type(original_name)[0] or "application/octet-stream"

        if storage_client:
            storage_path = f"trip-images/{generated_name}"
            upload_payload = image.stream.read()
            storage_client.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
                storage_path,
                upload_payload,
                {"content-type": content_type},
            )
            public_url = storage_client.storage.from_(SUPABASE_STORAGE_BUCKET).get_public_url(storage_path)
        else:
            storage_path = generated_name
            image.save(UPLOAD_DIR / generated_name)
            public_url = url_for("static", filename=f"uploads/{generated_name}")

        saved_images.append(
            {
                "file_name": generated_name,
                "original_name": original_name,
                "storage_path": storage_path,
                "public_url": public_url,
            }
        )
    return saved_images


@app.route("/", methods=["GET"])
def index():
    selected_month = normalize_month_value(request.args.get("month"))
    trips, summary = fetch_trips(selected_month)
    return render_template(
        "index.html",
        trips=trips,
        summary=summary,
        selected_month=selected_month,
        today=date.today().isoformat(),
    )


@app.route("/trips", methods=["POST"])
def create_trip():
    trip_date = request.form.get("trip_date", "").strip()
    origin = request.form.get("origin", "").strip()
    destination = request.form.get("destination", "").strip()
    note = request.form.get("note", "").strip()
    owner = request.form.get("owner", "").strip()

    if not trip_date or not origin or not destination:
        flash("กรอกวันที่ ต้นทาง และปลายทางให้ครบก่อนบันทึก", "error")
        return redirect(url_for("index", month=trip_date[:7] if trip_date else None))

    try:
        saved_images = save_images(request.files.getlist("images"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index", month=trip_date[:7]))

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO trips (trip_date, origin, destination, note, owner, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (trip_date, origin, destination, note, owner, datetime.utcnow()),
        )
        trip_id = cursor.fetchone()[0]

    if saved_images:
        with db.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO trip_images (trip_id, file_name, original_name, storage_path, public_url)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        trip_id,
                        image_record["file_name"],
                        image_record["original_name"],
                        image_record["storage_path"],
                        image_record["public_url"],
                    )
                    for image_record in saved_images
                ],
            )

    db.commit()
    flash("บันทึกงานวิ่งเรียบร้อยแล้ว", "success")
    return redirect(url_for("index", month=trip_date[:7]))


@app.route("/trips/<int:trip_id>/edit", methods=["POST"])
def update_trip(trip_id: int):
    trip_date   = request.form.get("trip_date",   "").strip()
    origin      = request.form.get("origin",      "").strip()
    destination = request.form.get("destination", "").strip()
    owner       = request.form.get("owner",       "").strip()
    note        = request.form.get("note",        "").strip()
    month       = request.form.get("month",       "").strip()

    if not trip_date or not origin or not destination:
        flash("กรอกวันที่ ต้นทาง และปลายทางให้ครบก่อนบันทึก", "error")
        return redirect(url_for("index", month=month or None))

    # ── parse image-delete ids (must belong to this trip) ──
    delete_ids: list[int] = []
    for raw in request.form.getlist("delete_image_ids"):
        try:
            delete_ids.append(int(raw))
        except (TypeError, ValueError):
            continue

    # ── save new images (may raise ValueError) ──
    try:
        new_images = save_images(request.files.getlist("images"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index", month=month or trip_date[:7]))

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            UPDATE trips
            SET trip_date=%s, origin=%s, destination=%s, owner=%s, note=%s
            WHERE id=%s
            """,
            (trip_date, origin, destination, owner, note, trip_id),
        )

    # ── delete selected images ──
    removed_records: list[tuple[str, str]] = []   # (file_name, storage_path)
    if delete_ids:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT file_name, storage_path FROM trip_images "
                "WHERE trip_id = %s AND id = ANY(%s)",
                (trip_id, delete_ids),
            )
            removed_records = [(r[0], r[1]) for r in cursor.fetchall()]
            cursor.execute(
                "DELETE FROM trip_images WHERE trip_id = %s AND id = ANY(%s)",
                (trip_id, delete_ids),
            )

    # ── insert new images ──
    if new_images:
        with db.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO trip_images (trip_id, file_name, original_name, storage_path, public_url)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        trip_id,
                        rec["file_name"],
                        rec["original_name"],
                        rec["storage_path"],
                        rec["public_url"],
                    )
                    for rec in new_images
                ],
            )

    db.commit()

    # ── remove files from local disk + storage bucket ──
    storage_client = get_storage_client()
    storage_paths_to_remove: list[str] = []
    for file_name, storage_path in removed_records:
        if storage_path:
            storage_paths_to_remove.append(storage_path)
        local_path = UPLOAD_DIR / file_name
        if local_path.exists():
            local_path.unlink()
    if storage_client and storage_paths_to_remove:
        try:
            storage_client.storage.from_(SUPABASE_STORAGE_BUCKET).remove(storage_paths_to_remove)
        except Exception:
            pass

    flash("แก้ไขรายการเรียบร้อยแล้ว", "success")
    return redirect(url_for("index", month=month or trip_date[:7]))


@app.route("/trips/<int:trip_id>/delete", methods=["POST"])
def delete_trip(trip_id: int):
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT file_name, storage_path FROM trip_images WHERE trip_id = %s", (trip_id,))
        images = cursor.fetchall()
        cursor.execute("DELETE FROM trip_images WHERE trip_id = %s", (trip_id,))
        cursor.execute("DELETE FROM trips WHERE id = %s", (trip_id,))
    db.commit()

    storage_client = get_storage_client()
    storage_paths = []
    for image in images:
        file_name = image[0]
        storage_path = image[1]
        storage_paths.append(storage_path)
        image_path = UPLOAD_DIR / file_name
        if image_path.exists():
            image_path.unlink()

    if storage_client and storage_paths:
        storage_client.storage.from_(SUPABASE_STORAGE_BUCKET).remove(storage_paths)

    flash("ลบรายการแล้ว", "success")
    return redirect(url_for("index", month=request.args.get("month")))


@app.route("/export/monthly.pdf", methods=["GET"])
def export_monthly_pdf():
    selected_month = normalize_month_value(request.args.get("month"))
    trips, summary = fetch_trips(selected_month)
    month_label = datetime.strptime(selected_month, "%Y-%m").strftime("%B %Y")
    export_filename = f"My Transport {selected_month}_{datetime.now().strftime('%H%M%S')}.pdf"

    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#111111")
    title_style.fontName = PDF_FONT_BOLD

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName=PDF_FONT_REGULAR,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#333333"),
    )

    story = [
        Paragraph("My Transport", title_style),
        Spacer(1, 6),
        Paragraph(f"สรุปรายเดือน {month_label}", body_style),
        Spacer(1, 10),
        Paragraph(
            f"จำนวนงานวิ่ง {summary['count']} | จำนวนวัน {summary['days']}",
            body_style,
        ),
        Spacer(1, 14),
    ]

    table_data = [["วันที่", "จาก", "ไป", "งานของ", "หมายเหตุ"]]
    for trip in sorted(trips, key=lambda item: item["trip_date"]):
        note = trip["note"] or "-"
        owner = trip["owner"] or "-"
        table_data.append([trip["trip_date"], trip["origin"], trip["destination"], owner, note])

    if len(table_data) == 1:
        table_data.append(["-", "-", "-", "-", "ยังไม่มีรายการในเดือนนี้"])

    table = Table(
        table_data,
        colWidths=[24 * mm, 42 * mm, 42 * mm, 30 * mm, 44 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111111")),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#222222")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
                ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), PDF_FONT_REGULAR),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(table)

    doc.build(story)
    pdf_buffer.seek(0)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=export_filename,
        mimetype="application/pdf",
    )


@app.route("/api/suggestions/<field>", methods=["GET"])
def get_suggestions(field: str):
    if field not in VALID_SUGGESTION_FIELDS:
        return jsonify({"error": "invalid field"}), 400
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT id, value FROM suggestions WHERE field = %s ORDER BY value ASC",
            (field,),
        )
        rows = cursor.fetchall()
    return jsonify([{"id": r[0], "value": r[1]} for r in rows])


@app.route("/api/suggestions/<field>", methods=["POST"])
def add_suggestion(field: str):
    if field not in VALID_SUGGESTION_FIELDS:
        return jsonify({"error": "invalid field"}), 400
    value = (request.get_json(silent=True) or {}).get("value", "").strip()
    if not value:
        return jsonify({"error": "value required"}), 400
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO suggestions (field, value, created_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (field, value) DO NOTHING
            RETURNING id
            """,
            (field, value, datetime.utcnow()),
        )
        row = cursor.fetchone()
        if row:
            suggestion_id = row[0]
        else:
            cursor.execute(
                "SELECT id FROM suggestions WHERE field = %s AND value = %s",
                (field, value),
            )
            suggestion_id = cursor.fetchone()[0]
    db.commit()
    return jsonify({"id": suggestion_id, "value": value})


@app.route("/api/suggestions/<field>/<int:suggestion_id>", methods=["PUT"])
def update_suggestion(field: str, suggestion_id: int):
    if field not in VALID_SUGGESTION_FIELDS:
        return jsonify({"error": "invalid field"}), 400
    value = (request.get_json(silent=True) or {}).get("value", "").strip()
    if not value:
        return jsonify({"error": "value required"}), 400
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE suggestions SET value = %s WHERE id = %s AND field = %s",
            (value, suggestion_id, field),
        )
    db.commit()
    return jsonify({"id": suggestion_id, "value": value})


@app.route("/api/suggestions/<field>/<int:suggestion_id>", methods=["DELETE"])
def delete_suggestion(field: str, suggestion_id: int):
    if field not in VALID_SUGGESTION_FIELDS:
        return jsonify({"error": "invalid field"}), 400
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM suggestions WHERE id = %s AND field = %s",
            (suggestion_id, field),
        )
    db.commit()
    return jsonify({"ok": True})


init_db()
register_pdf_fonts()


if __name__ == "__main__":
    app.run(debug=True)
