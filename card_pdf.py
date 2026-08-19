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

PDF_IMAGE_QUALITY = 65
PDF_IMAGE_PIXELS_PER_MM = 6


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
            pixel_width = max(220, int(width / mm * PDF_IMAGE_PIXELS_PER_MM))
            pixel_height = max(170, int(height / mm * PDF_IMAGE_PIXELS_PER_MM))
            fitted = ImageOps.fit(
                source,
                (pixel_width, pixel_height),
                method=PillowImage.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = BytesIO()
            fitted.save(
                output,
                format="JPEG",
                quality=PDF_IMAGE_QUALITY,
                optimize=False,
                subsampling=2,
            )
            output.seek(0)
        return Image(output, width=width, height=height)
    except Exception:
        return None


def _profile_flowable(picture_url: str | None, size: float) -> Image | None:
    if not picture_url or not picture_url.startswith("https://"):
        return None
    try:
        request = urllib.request.Request(
            picture_url,
            headers={"User-Agent": "MyTransportCardPDF/1.0"},
        )
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = response.read(512 * 1024)
        with PillowImage.open(BytesIO(payload)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            fitted = ImageOps.fit(
                source,
                (180, 180),
                method=PillowImage.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = BytesIO()
            fitted.save(output, format="JPEG", quality=PDF_IMAGE_QUALITY, subsampling=2)
            output.seek(0)
        return Image(output, width=size, height=size)
    except Exception:
        return None


def _photo_strip(
    images: list[dict],
    upload_dir: Path,
    styles: dict[str, ParagraphStyle],
) -> Table:
    primary_images = images[:2]
    if not primary_images:
        return Table(
            [[Paragraph("ไม่มีรูปแนบ", styles["photo_empty"])]],
            colWidths=[68 * mm],
            rowHeights=[21 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F0E8")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D1C1")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        )

    cells: list[object] = []
    widths = [32 * mm] * len(primary_images)
    if len(primary_images) == 1:
        widths = [68 * mm]
        photo_width = 68 * mm
    else:
        photo_width = 32 * mm

    for image_record in primary_images:
        photo = _photo_flowable(image_record, upload_dir, photo_width, 21 * mm)
        cells.append(photo or Table(
            [[Paragraph("โหลดรูปไม่ได้", styles["photo_empty"])]],
            colWidths=[photo_width],
            rowHeights=[21 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F0E8")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D1C1")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        ))

    strip = Table([cells], colWidths=widths, rowHeights=[21 * mm], hAlign="LEFT")
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


def _additional_photo_row(
    image_records: list[dict],
    *,
    first_number: int,
    total_images: int,
    trip_index: int,
    upload_dir: Path,
    styles: dict[str, ParagraphStyle],
) -> Table:
    photo_width = 38.5 * mm
    photo_height = 22 * mm
    cells: list[object] = []
    for image_record in image_records:
        photo = _photo_flowable(image_record, upload_dir, photo_width, photo_height)
        cells.append(photo or Table(
            [[Paragraph("โหลดรูปไม่ได้", styles["photo_empty"])]],
            colWidths=[photo_width],
            rowHeights=[photo_height],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F0E8")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D1C1")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        ))

    gallery = Table(
        [cells],
        colWidths=[40.5 * mm] * len(cells),
        rowHeights=[24 * mm],
        hAlign="CENTER",
    )
    gallery.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
            ]
        )
    )

    last_number = first_number + len(image_records) - 1
    heading = Paragraph(
        f"งาน #{trip_index:02d} · รูปเพิ่มเติม {first_number}-{last_number} จาก {total_images} รูป",
        styles["gallery_heading"],
    )
    block = Table([[heading], [gallery]], colWidths=[170 * mm], hAlign="CENTER")
    block.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#E9DFC9")),
                ("BACKGROUND", (0, 1), (0, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CFC5B2")),
                ("LEFTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 4 * mm),
                ("TOPPADDING", (0, 0), (0, 0), 1.2 * mm),
                ("BOTTOMPADDING", (0, 0), (0, 0), 1.2 * mm),
                ("LEFTPADDING", (0, 1), (0, 1), 4 * mm),
                ("RIGHTPADDING", (0, 1), (0, 1), 4 * mm),
                ("TOPPADDING", (0, 1), (0, 1), 1.2 * mm),
                ("BOTTOMPADDING", (0, 1), (0, 1), 1.2 * mm),
            ]
        )
    )
    return block


def _trip_card(
    trip: dict,
    index: int,
    upload_dir: Path,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    date_value = datetime.strptime(trip["trip_date"], "%Y-%m-%d")
    date_label = date_value.strftime("%d/%m/%Y")
    route = f"{trip.get('origin') or '-'}  →  {trip.get('destination') or '-'}"
    expense = Decimal(str(trip.get("toll_fee") or "0"))

    card_header = Table(
        [[
            Paragraph(f"งาน #{index:02d} · {date_label}", styles["date"]),
            _paragraph(route, styles["route"]),
        ]],
        colWidths=[38 * mm, 132 * mm],
    )
    card_header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#B98C3D")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#1C1A16")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 3 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 4 * mm),
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
                ("TOPPADDING", (0, 0), (-1, -1), 0.25 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.25 * mm),
            ]
        )
    )

    images = list(trip.get("images") or [])
    photos = _photo_strip(images, upload_dir, styles)
    image_count = len(images)
    photo_content: list[object] = [photos]

    body = Table(
        [[info, photo_content]],
        colWidths=[98 * mm, 72 * mm],
    )
    body.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 2 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
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
                ("LEFTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 2 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4 * mm),
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
    additional_images = images[2:]
    flowables: list[object] = [
        KeepTogether([card, Spacer(1, 1.5 * mm if additional_images else 2.8 * mm)])
    ]
    for offset in range(0, len(additional_images), 4):
        row_images = additional_images[offset:offset + 4]
        row = _additional_photo_row(
            row_images,
            first_number=offset + 3,
            total_images=image_count,
            trip_index=index,
            upload_dir=upload_dir,
            styles=styles,
        )
        is_last_row = offset + 4 >= len(additional_images)
        flowables.append(KeepTogether([row, Spacer(1, 2.8 * mm if is_last_row else 1.5 * mm)]))
    return flowables


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
        bottomMargin=14 * mm,
        title=f"My Transport - {_month_label(selected_month)}",
        author=current_user.get("name") or current_user.get("email") or "My Transport",
    )
    sample = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("CardTitle", parent=sample["Title"], fontName=font_bold, fontSize=20, leading=23, textColor=colors.HexColor("#111111"), alignment=0),
        "subtitle": ParagraphStyle("CardSubtitle", parent=sample["BodyText"], fontName=font_regular, fontSize=8.5, leading=11, textColor=colors.HexColor("#333333")),
        "header_small": ParagraphStyle("HeaderSmall", parent=sample["BodyText"], fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#666666")),
        "date": ParagraphStyle("CardDate", parent=sample["BodyText"], fontName=font_regular, fontSize=7, leading=9, textColor=colors.white),
        "route": ParagraphStyle("CardRoute", parent=sample["BodyText"], fontName=font_bold, fontSize=11, leading=13, textColor=colors.white),
        "label": ParagraphStyle("CardLabel", parent=sample["BodyText"], fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#81786A")),
        "value": ParagraphStyle("CardValue", parent=sample["BodyText"], fontName=font_bold, fontSize=8.5, leading=10, textColor=colors.HexColor("#29251E")),
        "money": ParagraphStyle("CardMoney", parent=sample["BodyText"], fontName=font_bold, fontSize=8.5, leading=10, textColor=colors.HexColor("#9A6D20")),
        "note": ParagraphStyle("CardNote", parent=sample["BodyText"], fontName=font_regular, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#494339")),
        "photo_empty": ParagraphStyle("PhotoEmpty", parent=sample["BodyText"], fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#9A9285"), alignment=1),
        "gallery_heading": ParagraphStyle("GalleryHeading", parent=sample["BodyText"], fontName=font_bold, fontSize=7.5, leading=9, textColor=colors.HexColor("#5C4A2C")),
        "empty": ParagraphStyle("Empty", parent=sample["BodyText"], fontName=font_regular, fontSize=11, leading=16, textColor=colors.HexColor("#746C5E"), alignment=1),
    }

    user_name = current_user.get("name") or current_user.get("email") or "-"
    user_email = current_user.get("email") or "-"
    profile_mark = _profile_flowable(current_user.get("picture"), 10 * mm) or Table(
        [[_paragraph((user_name or "?")[:1].upper(), styles["value"])]],
        colWidths=[10 * mm],
        rowHeights=[10 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2E3BF")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7BD78")),
            ]
        ),
    )
    profile_table = Table(
        [[
            profile_mark,
            [
                Paragraph("ผู้ใช้งาน", styles["header_small"]),
                _paragraph(user_name, styles["subtitle"]),
                _paragraph(user_email, styles["header_small"]),
            ],
        ]],
        colWidths=[13 * mm, 100 * mm],
    )
    profile_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story: list[object] = [
        Paragraph("My Transport", styles["title"]),
        Spacer(1, 1.2 * mm),
        profile_table,
        Spacer(1, 1.5 * mm),
        Paragraph(f"สรุปรายเดือน {_month_label(selected_month)}", styles["subtitle"]),
    ]
    if selected_vehicle_type:
        story.append(Paragraph(f"ประเภทรถ: {escape(selected_vehicle_type)}", styles["subtitle"]))
    story.extend(
        [
            Spacer(1, 1 * mm),
            Paragraph(
                (
                    f"จำนวนงานวิ่ง {summary.get('count', 0)} | "
                    f"จำนวนวัน {summary.get('days', 0)} | "
                    f"รูปแนบ {summary.get('attachments', 0)} | "
                    f"รวมค่าใช้จ่าย {Decimal(str(summary.get('total_expenses') or '0')):,.2f} บาท"
                ),
                styles["subtitle"],
            ),
            Spacer(1, 3.5 * mm),
        ]
    )

    if trips:
        for index, trip in enumerate(trips, start=1):
            story.extend(_trip_card(trip, index, upload_dir, styles))
    else:
        story.append(Table([[Paragraph("ยังไม่มีรายการในเดือนนี้", styles["empty"])]], colWidths=[170 * mm], rowHeights=[35 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3EFE6")), ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#D7CDBA")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])))

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
