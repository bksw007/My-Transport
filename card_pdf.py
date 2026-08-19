from __future__ import annotations

import urllib.request
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PillowImage, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


THAI_MONTHS = (
    "",
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
)


def _paragraph(value: object, style: ParagraphStyle, fallback: str = "-") -> Paragraph:
    return Paragraph(escape(str(value or fallback)), style)


def _month_label(month_value: str) -> str:
    selected = datetime.strptime(month_value, "%Y-%m")
    return f"{THAI_MONTHS[selected.month]} {selected.year + 543}"


def _read_photo(image_record: dict, upload_dir: Path) -> bytes | None:
    file_name = Path(str(image_record.get("file_name") or "")).name
    if file_name:
        local_path = upload_dir / file_name
        if local_path.is_file():
            try:
                return local_path.read_bytes()
            except OSError:
                pass

    image_url = str(image_record.get("url") or "")
    if not image_url.startswith(("https://", "http://")):
        return None
    try:
        request = urllib.request.Request(
            image_url,
            headers={"User-Agent": "MyTransportCardPDF/1.0"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.read(12 * 1024 * 1024)
    except Exception:
        return None


def _photo_flowable(
    image_record: dict,
    upload_dir: Path,
    width: float,
    height: float,
) -> Image | None:
    payload = _read_photo(image_record, upload_dir)
    if not payload:
        return None
    try:
        with PillowImage.open(BytesIO(payload)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            pixel_width = max(320, int(width / mm * 18))
            pixel_height = max(240, int(height / mm * 18))
            fitted = ImageOps.fit(
                source,
                (pixel_width, pixel_height),
                method=PillowImage.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = BytesIO()
            fitted.save(output, format="JPEG", quality=84, optimize=True)
            output.seek(0)
        return Image(output, width=width, height=height)
    except Exception:
        return None


def _photo_strip(
    images: list[dict],
    upload_dir: Path,
    styles: dict[str, ParagraphStyle],
) -> Table:
    loaded_photos = []
    for image_record in images:
        photo = _photo_flowable(image_record, upload_dir, 32 * mm, 27 * mm)
        if photo is not None:
            loaded_photos.append(photo)
        if len(loaded_photos) == 2:
            break

    if not loaded_photos:
        return Table(
            [[Paragraph("ไม่มีรูปแนบ", styles["photo_empty"])]],
            colWidths=[68 * mm],
            rowHeights=[27 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F0E8")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D1C1")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        )

    cells: list[object] = list(loaded_photos)
    widths = [32 * mm] * len(cells)
    if len(cells) == 1:
        widths = [68 * mm]
        cells = [_photo_flowable(images[0], upload_dir, 68 * mm, 27 * mm) or cells[0]]

    strip = Table([cells], colWidths=widths, rowHeights=[27 * mm], hAlign="LEFT")
    strip.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return strip


def _trip_card(
    trip: dict,
    index: int,
    upload_dir: Path,
    styles: dict[str, ParagraphStyle],
) -> KeepTogether:
    date_value = datetime.strptime(trip["trip_date"], "%Y-%m-%d")
    date_label = date_value.strftime("%d/%m/%Y")
    route = f"{trip.get('origin') or '-'}  →  {trip.get('destination') or '-'}"
    expense = Decimal(str(trip.get("toll_fee") or "0"))

    card_header = Table(
        [[
            Paragraph(f"งาน #{index:02d}<br/><b>{date_label}</b>", styles["date"]),
            _paragraph(route, styles["route"]),
        ]],
        colWidths=[29 * mm, 141 * mm],
    )
    card_header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#B98C3D")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#1C1A16")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 5 * mm),
            ]
        )
    )

    info = Table(
        [
            [Paragraph("งานของ", styles["label"]), _paragraph(trip.get("owner"), styles["value"])],
            [Paragraph("ประเภทรถ", styles["label"]), _paragraph(trip.get("vehicle_type"), styles["value"])],
            [Paragraph("ค่าใช้จ่าย", styles["label"]), Paragraph(f"{expense:,.2f} บาท", styles["money"])],
        ],
        colWidths=[22 * mm, 72 * mm],
    )
    info.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0.8 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8 * mm),
            ]
        )
    )

    photos = _photo_strip(list(trip.get("images") or []), upload_dir, styles)
    image_count = len(trip.get("images") or [])
    photo_content: list[object] = [photos]
    if image_count > 2:
        photo_content.append(Spacer(1, 1.2 * mm))
        photo_content.append(Paragraph(f"แสดง 2 จาก {image_count} รูป", styles["photo_count"]))

    body = Table(
        [[info, photo_content]],
        colWidths=[98 * mm, 72 * mm],
    )
    body.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 5 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 3 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )

    note = Table(
        [[Paragraph("หมายเหตุ", styles["label"]), _paragraph(trip.get("note"), styles["note"])]],
        colWidths=[24 * mm, 146 * mm],
    )
    note.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#DDD6C8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 5 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 2 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )

    card = Table([[card_header], [body], [note]], colWidths=[170 * mm], hAlign="CENTER")
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CFC5B2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return KeepTogether([card, Spacer(1, 5 * mm)])


def build_card_report(
    target,
    *,
    trips: list[dict],
    summary: dict,
    selected_month: str,
    selected_vehicle_type: str,
    current_user: dict,
    upload_dir: Path,
    font_regular: str,
    font_bold: str,
) -> None:
    doc = SimpleDocTemplate(
        target,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"My Transport - {_month_label(selected_month)}",
        author=current_user.get("name") or current_user.get("email") or "My Transport",
    )
    sample = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("CardTitle", parent=sample["Title"], fontName=font_bold, fontSize=23, leading=27, textColor=colors.HexColor("#171510"), alignment=0),
        "subtitle": ParagraphStyle("CardSubtitle", parent=sample["BodyText"], fontName=font_regular, fontSize=9, leading=13, textColor=colors.HexColor("#6D665A")),
        "summary_label": ParagraphStyle("SummaryLabel", parent=sample["BodyText"], fontName=font_regular, fontSize=7.5, leading=10, textColor=colors.HexColor("#746C5E")),
        "summary_value": ParagraphStyle("SummaryValue", parent=sample["BodyText"], fontName=font_bold, fontSize=14, leading=18, textColor=colors.HexColor("#1C1A16")),
        "date": ParagraphStyle("CardDate", parent=sample["BodyText"], fontName=font_regular, fontSize=7.5, leading=11, textColor=colors.white),
        "route": ParagraphStyle("CardRoute", parent=sample["BodyText"], fontName=font_bold, fontSize=13, leading=17, textColor=colors.white),
        "label": ParagraphStyle("CardLabel", parent=sample["BodyText"], fontName=font_regular, fontSize=7.5, leading=11, textColor=colors.HexColor("#81786A")),
        "value": ParagraphStyle("CardValue", parent=sample["BodyText"], fontName=font_bold, fontSize=9.5, leading=13, textColor=colors.HexColor("#29251E")),
        "money": ParagraphStyle("CardMoney", parent=sample["BodyText"], fontName=font_bold, fontSize=10, leading=13, textColor=colors.HexColor("#9A6D20")),
        "note": ParagraphStyle("CardNote", parent=sample["BodyText"], fontName=font_regular, fontSize=8.5, leading=12, textColor=colors.HexColor("#494339")),
        "photo_empty": ParagraphStyle("PhotoEmpty", parent=sample["BodyText"], fontName=font_regular, fontSize=8, leading=11, textColor=colors.HexColor("#9A9285"), alignment=1),
        "photo_count": ParagraphStyle("PhotoCount", parent=sample["BodyText"], fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#81786A"), alignment=2),
        "empty": ParagraphStyle("Empty", parent=sample["BodyText"], fontName=font_regular, fontSize=11, leading=16, textColor=colors.HexColor("#746C5E"), alignment=1),
        "footer": ParagraphStyle("Footer", parent=sample["BodyText"], fontName=font_regular, fontSize=7.5, leading=10, textColor=colors.HexColor("#8B8377")),
    }

    user_name = current_user.get("name") or current_user.get("email") or "-"
    header = Table(
        [[
            [Paragraph("MY TRANSPORT", styles["title"]), Paragraph(f"รายงานแบบการ์ด · {_month_label(selected_month)}", styles["subtitle"])],
            [Paragraph("จัดทำโดย", styles["summary_label"]), _paragraph(user_name, styles["value"])],
        ]],
        colWidths=[124 * mm, 46 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))

    summary_items = [
        ("งานวิ่ง", str(summary.get("count", 0))),
        ("จำนวนวัน", str(summary.get("days", 0))),
        ("รูปแนบ", str(summary.get("attachments", 0))),
        ("ค่าใช้จ่ายรวม", f"{Decimal(str(summary.get('total_expenses') or '0')):,.2f} บาท"),
    ]
    summary_table = Table(
        [[
            [Paragraph(label, styles["summary_label"]), Paragraph(value, styles["summary_value"])]
            for label, value in summary_items
        ]],
        colWidths=[42.5 * mm] * 4,
    )
    summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3EFE6")), ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D7CDBA")), ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7CDBA")), ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

    story: list[object] = [header, Spacer(1, 5 * mm)]
    if selected_vehicle_type:
        story.extend([Paragraph(f"กรองประเภทรถ: {escape(selected_vehicle_type)}", styles["subtitle"]), Spacer(1, 2 * mm)])
    story.extend([summary_table, Spacer(1, 7 * mm)])

    if trips:
        for index, trip in enumerate(trips, start=1):
            story.append(_trip_card(trip, index, upload_dir, styles))
    else:
        story.append(Table([[Paragraph("ยังไม่มีรายการในเดือนนี้", styles["empty"])]], colWidths=[170 * mm], rowHeights=[55 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3EFE6")), ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D7CDBA")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])))

    def draw_page(canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#B98C3D"))
        canvas.setLineWidth(1.2)
        canvas.line(14 * mm, 10 * mm, 196 * mm, 10 * mm)
        canvas.setFont(font_regular, 7.5)
        canvas.setFillColor(colors.HexColor("#8B8377"))
        canvas.drawString(14 * mm, 6.5 * mm, "My Transport · Card Report")
        canvas.drawRightString(196 * mm, 6.5 * mm, f"หน้า {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
