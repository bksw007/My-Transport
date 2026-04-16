from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "transport.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "my-transport-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_: object | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_date TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trip_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips (id) ON DELETE CASCADE
            );
            """
        )
        connection.commit()


def register_pdf_fonts() -> None:
    global PDF_FONT_REGULAR, PDF_FONT_BOLD

    font_candidates = [
        (
            "MyTransportThai",
            BASE_DIR / "assets" / "fonts" / "NotoSansThai-Regular.ttf",
            BASE_DIR / "assets" / "fonts" / "NotoSansThai-Bold.ttf",
        ),
        (
            "MyTransportThaiFallback",
            Path("/System/Library/Fonts/ThonburiUI.ttc"),
            Path("/System/Library/Fonts/ThonburiUI.ttc"),
        ),
        (
            "MyTransportThaiFallbackAlt",
            Path("/System/Library/Fonts/Supplemental/Silom.ttf"),
            Path("/System/Library/Fonts/Supplemental/Silom.ttf"),
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


def month_bounds(month_value: str | None) -> tuple[str, str]:
    if month_value:
        selected = datetime.strptime(month_value, "%Y-%m")
    else:
        today = date.today()
        selected = datetime(today.year, today.month, 1)

    if selected.month == 12:
        next_month = datetime(selected.year + 1, 1, 1)
    else:
        next_month = datetime(selected.year, selected.month + 1, 1)

    return selected.strftime("%Y-%m-%d"), next_month.strftime("%Y-%m-%d")


def fetch_trips(month_value: str | None) -> tuple[list[dict], dict]:
    start, end = month_bounds(month_value)
    db = get_db()
    rows = db.execute(
        """
        SELECT
            t.id,
            t.trip_date,
            t.origin,
            t.destination,
            t.note,
            GROUP_CONCAT(i.file_name, '||') AS image_names,
            GROUP_CONCAT(i.original_name, '||') AS original_names
        FROM trips t
        LEFT JOIN trip_images i ON i.trip_id = t.id
        WHERE t.trip_date >= ? AND t.trip_date < ?
        GROUP BY t.id
        ORDER BY t.trip_date DESC, t.id DESC
        """,
        (start, end),
    ).fetchall()

    trips = []
    for row in rows:
        image_names = row["image_names"].split("||") if row["image_names"] else []
        original_names = row["original_names"].split("||") if row["original_names"] else []
        images = [
            {
                "file_name": file_name,
                "original_name": original_name,
                "url": url_for("static", filename=f"uploads/{file_name}"),
            }
            for file_name, original_name in zip(image_names, original_names)
        ]
        trips.append(
            {
                "id": row["id"],
                "trip_date": row["trip_date"],
                "origin": row["origin"],
                "destination": row["destination"],
                "note": row["note"],
                "images": images,
            }
        )

    summary = {
        "count": len(trips),
        "days": len({trip["trip_date"] for trip in trips}),
        "attachments": sum(len(trip["images"]) for trip in trips),
    }
    return trips, summary


def save_images(files: Iterable) -> list[tuple[str, str]]:
    saved_images: list[tuple[str, str]] = []
    for image in files:
        if not image or not image.filename:
            continue
        if not is_allowed_file(image.filename):
            raise ValueError(f"ไฟล์ {image.filename} ไม่รองรับ")

        original_name = secure_filename(image.filename)
        suffix = Path(original_name).suffix.lower()
        generated_name = f"{uuid.uuid4().hex}{suffix}"
        image.save(UPLOAD_DIR / generated_name)
        saved_images.append((generated_name, original_name))
    return saved_images


@app.route("/", methods=["GET"])
def index():
    selected_month = request.args.get("month") or date.today().strftime("%Y-%m")
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

    if not trip_date or not origin or not destination:
        flash("กรอกวันที่ ต้นทาง และปลายทางให้ครบก่อนบันทึก", "error")
        return redirect(url_for("index", month=trip_date[:7] if trip_date else None))

    try:
        saved_images = save_images(request.files.getlist("images"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index", month=trip_date[:7]))

    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO trips (trip_date, origin, destination, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (trip_date, origin, destination, note, datetime.utcnow().isoformat()),
    )
    trip_id = cursor.lastrowid

    if saved_images:
        db.executemany(
            """
            INSERT INTO trip_images (trip_id, file_name, original_name)
            VALUES (?, ?, ?)
            """,
            [(trip_id, file_name, original_name) for file_name, original_name in saved_images],
        )

    db.commit()
    flash("บันทึกงานวิ่งเรียบร้อยแล้ว", "success")
    return redirect(url_for("index", month=trip_date[:7]))


@app.route("/trips/<int:trip_id>/delete", methods=["POST"])
def delete_trip(trip_id: int):
    db = get_db()
    images = db.execute("SELECT file_name FROM trip_images WHERE trip_id = ?", (trip_id,)).fetchall()
    db.execute("DELETE FROM trip_images WHERE trip_id = ?", (trip_id,))
    db.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
    db.commit()

    for image in images:
        image_path = UPLOAD_DIR / image["file_name"]
        if image_path.exists():
            image_path.unlink()

    flash("ลบรายการแล้ว", "success")
    return redirect(url_for("index", month=request.args.get("month")))


@app.route("/export/monthly.pdf", methods=["GET"])
def export_monthly_pdf():
    selected_month = request.args.get("month") or date.today().strftime("%Y-%m")
    trips, summary = fetch_trips(selected_month)
    month_label = datetime.strptime(selected_month, "%Y-%m").strftime("%B %Y")

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
    title_style.textColor = colors.HexColor("#f5f7ff")
    title_style.fontName = PDF_FONT_BOLD

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName=PDF_FONT_REGULAR,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#d7dbef"),
    )

    story = [
        Paragraph("My Transport", title_style),
        Spacer(1, 6),
        Paragraph(f"สรุปรายเดือน {month_label}", body_style),
        Spacer(1, 10),
        Paragraph(
            f"จำนวนงานวิ่ง {summary['count']} | จำนวนวัน {summary['days']} | รูปแนบ {summary['attachments']}",
            body_style,
        ),
        Spacer(1, 14),
    ]

    table_data = [["วันที่", "เส้นทาง", "หมายเหตุ", "รูป"]]
    for trip in sorted(trips, key=lambda item: item["trip_date"]):
        route = f"{trip['origin']} -> {trip['destination']}"
        note = trip["note"] or "-"
        table_data.append([trip["trip_date"], route, note, str(len(trip["images"]))])

    if len(table_data) == 1:
        table_data.append(["-", "-", "ยังไม่มีรายการในเดือนนี้", "0"])

    table = Table(table_data, colWidths=[26 * mm, 55 * mm, 78 * mm, 20 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#151a28")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0d111b")),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#d7dbef")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2c344b")),
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

    doc.build(
        story,
        onFirstPage=_paint_pdf_background,
        onLaterPages=_paint_pdf_background,
    )
    pdf_buffer.seek(0)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"my-transport-{selected_month}.pdf",
        mimetype="application/pdf",
    )


def _paint_pdf_background(canvas, doc) -> None:  # type: ignore[no-untyped-def]
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#090b11"))
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
    canvas.restoreState()


init_db()
register_pdf_fonts()


if __name__ == "__main__":
    app.run(debug=True)
