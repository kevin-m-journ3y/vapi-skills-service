# app/admin/pdf_generator.py - PDF report generation using reportlab
import io
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Optional
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


# Brand colours
NAVY = colors.HexColor("#1B1464")
LIGHT_GREY = colors.HexColor("#F5F5F5")
MID_GREY = colors.HexColor("#E0E0E0")
DARK_GREY = colors.HexColor("#666666")
WHITE = colors.white
BLACK = colors.black
ACCENT_BLUE = colors.HexColor("#3B82F6")
ACCENT_GREEN = colors.HexColor("#22C55E")
ACCENT_RED = colors.HexColor("#EF4444")
ACCENT_AMBER = colors.HexColor("#F59E0B")


def get_styles():
    """Get custom paragraph styles for reports."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='ReportTitle',
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=NAVY,
        spaceAfter=4*mm,
    ))

    styles.add(ParagraphStyle(
        name='ReportSubtitle',
        fontName='Helvetica',
        fontSize=11,
        leading=14,
        textColor=DARK_GREY,
        spaceAfter=6*mm,
    ))

    styles.add(ParagraphStyle(
        name='SectionHeading',
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=NAVY,
        spaceBefore=6*mm,
        spaceAfter=3*mm,
    ))

    styles.add(ParagraphStyle(
        name='SubSectionHeading',
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=NAVY,
        spaceBefore=4*mm,
        spaceAfter=2*mm,
    ))

    styles.add(ParagraphStyle(
        name='BodyText2',
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=BLACK,
    ))

    styles.add(ParagraphStyle(
        name='SmallGrey',
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=DARK_GREY,
    ))

    styles.add(ParagraphStyle(
        name='BulletItem',
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=BLACK,
        leftIndent=12,
        bulletIndent=0,
    ))

    styles.add(ParagraphStyle(
        name='RiskItem',
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=ACCENT_RED,
        leftIndent=12,
        bulletIndent=0,
    ))

    styles.add(ParagraphStyle(
        name='FooterText',
        fontName='Helvetica',
        fontSize=7,
        leading=9,
        textColor=DARK_GREY,
        alignment=TA_CENTER,
    ))

    return styles


def _build_header(tenant_name: str, report_title: str, period_label: str, styles) -> list:
    """Build the common report header with tenant branding."""
    elements = []

    # Tenant name as brand header
    elements.append(Paragraph(tenant_name, styles['ReportTitle']))
    elements.append(Paragraph(report_title, styles['SectionHeading']))
    elements.append(Paragraph(period_label, styles['ReportSubtitle']))
    elements.append(HRFlowable(
        width="100%", thickness=1, color=NAVY,
        spaceAfter=4*mm, spaceBefore=2*mm
    ))

    return elements


def _format_hours(hours: float) -> str:
    """Format hours for display."""
    if hours == 0:
        return "-"
    return f"{hours:.1f}"


def _add_footer(canvas, doc):
    """Add footer to each page."""
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(DARK_GREY)
    footer_text = f"Generated {datetime.now().strftime('%d %b %Y at %I:%M %p')}  |  Powered by JOURN3Y"
    canvas.drawCentredString(doc.pagesize[0] / 2, 12*mm, footer_text)
    # Page number
    canvas.drawRightString(doc.pagesize[0] - 15*mm, 12*mm, f"Page {doc.page}")
    canvas.restoreState()


# ============================================
# REPORT 1: WEEKLY PAYROLL SUMMARY
# ============================================

def generate_payroll_pdf(
    tenant_name: str,
    week_start: date,
    week_end: date,
    entries: List[Dict[str, Any]],
    users: Dict[str, str],
    break_minutes: int = 0,
    break_threshold_hours: float = 4.0,
) -> bytes:
    """
    Generate a weekly payroll PDF.

    Args:
        tenant_name: Company name for header
        week_start: Monday of the report week
        week_end: Sunday of the report week
        entries: List of timesheet entries with user_id, work_date, hours_worked
        users: Dict of user_id -> user_name
        break_minutes: Minutes to deduct per day (0 = no deduction)
        break_threshold_hours: Only deduct break if worked more than this
    """
    buffer = io.BytesIO()
    styles = get_styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15*mm,
        rightMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=20*mm,
    )

    elements = []

    # Header
    period_label = f"Week: {week_start.strftime('%d %b %Y')} - {week_end.strftime('%d %b %Y')}"
    elements.extend(_build_header(tenant_name, "Weekly Payroll Summary", period_label, styles))

    # Break deduction note
    if break_minutes > 0:
        note = (
            f"<b>Break Deduction:</b> {break_minutes} minutes deducted per day "
            f"where hours worked exceed {break_threshold_hours:.1f}h"
        )
        elements.append(Paragraph(note, styles['SmallGrey']))
        elements.append(Spacer(1, 3*mm))

    # Build person x day grid
    # Collect days in the week (Mon-Sun)
    from datetime import timedelta
    days = []
    current = week_start
    while current <= week_end:
        days.append(current)
        current += timedelta(days=1)

    # Group entries by user
    user_hours = {}  # user_id -> {date_str: hours}
    for entry in entries:
        uid = entry.get("user_id")
        work_date_str = entry.get("work_date")
        hours = float(entry.get("hours_worked", 0))
        if uid not in user_hours:
            user_hours[uid] = {}
        # Accumulate hours if multiple entries on same day
        user_hours[uid][work_date_str] = user_hours[uid].get(work_date_str, 0) + hours

    # Sort users by name
    sorted_users = sorted(user_hours.keys(), key=lambda uid: users.get(uid, "Unknown"))

    # Build table data
    day_labels = [d.strftime("%a\n%d %b") for d in days]
    header_row = ["Name"] + day_labels + ["Total\nHours"]
    if break_minutes > 0:
        header_row.append("Payable\nHours")

    table_data = [header_row]

    break_hours = break_minutes / 60.0

    for uid in sorted_users:
        name = users.get(uid, "Unknown")
        row = [name]
        total = 0
        payable = 0
        for d in days:
            ds = d.strftime("%Y-%m-%d")
            h = user_hours[uid].get(ds, 0)
            total += h
            # Calculate payable
            day_payable = h
            if break_minutes > 0 and h > break_threshold_hours:
                day_payable = max(0, h - break_hours)
            payable += day_payable
            row.append(_format_hours(h))
        row.append(f"{total:.1f}")
        if break_minutes > 0:
            row.append(f"{payable:.1f}")
        table_data.append(row)

    # Totals row
    totals_row = ["TOTAL"]
    grand_total = 0
    grand_payable = 0
    for d in days:
        ds = d.strftime("%Y-%m-%d")
        day_total = sum(user_hours[uid].get(ds, 0) for uid in sorted_users)
        grand_total += day_total
        # Payable per day per user
        day_payable_total = 0
        for uid in sorted_users:
            h = user_hours[uid].get(ds, 0)
            ph = h
            if break_minutes > 0 and h > break_threshold_hours:
                ph = max(0, h - break_hours)
            day_payable_total += ph
        grand_payable += day_payable_total
        totals_row.append(f"{day_total:.1f}")
    totals_row.append(f"{grand_total:.1f}")
    if break_minutes > 0:
        totals_row.append(f"{grand_payable:.1f}")
    table_data.append(totals_row)

    # Calculate column widths
    num_cols = len(header_row)
    name_width = 45*mm
    remaining = landscape(A4)[0] - 30*mm - name_width  # page width minus margins minus name col
    day_width = remaining / (num_cols - 1)

    col_widths = [name_width] + [day_width] * (num_cols - 1)

    # Create table
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # Style
    style_commands = [
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),

        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),

        # Name column bold
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),

        # Totals row
        ('BACKGROUND', (0, -1), (-1, -1), LIGHT_GREY),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),

        # Total hours column highlight
        ('BACKGROUND', (-2 if break_minutes > 0 else -1, 1), (-2 if break_minutes > 0 else -1, -2), LIGHT_GREY),
        ('FONTNAME', (-2 if break_minutes > 0 else -1, 1), (-2 if break_minutes > 0 else -1, -1), 'Helvetica-Bold'),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('LINEBELOW', (0, 0), (-1, 0), 1, NAVY),
        ('LINEABOVE', (0, -1), (-1, -1), 1, NAVY),
    ]

    # Payable column highlight (green header)
    if break_minutes > 0:
        style_commands.extend([
            ('BACKGROUND', (-1, 0), (-1, 0), ACCENT_GREEN),
            ('BACKGROUND', (-1, 1), (-1, -2), colors.HexColor("#F0FFF4")),
            ('FONTNAME', (-1, 1), (-1, -1), 'Helvetica-Bold'),
        ])

    # Alternate row shading
    for i in range(1, len(table_data) - 1):
        if i % 2 == 0:
            style_commands.append(
                ('BACKGROUND', (0, i), (-1, i), colors.HexColor("#FAFAFA"))
            )

    table.setStyle(TableStyle(style_commands))
    elements.append(table)

    # Summary box
    elements.append(Spacer(1, 6*mm))
    summary_text = f"<b>Total Workers:</b> {len(sorted_users)}  |  <b>Total Hours:</b> {grand_total:.1f}"
    if break_minutes > 0:
        summary_text += f"  |  <b>Payable Hours:</b> {grand_payable:.1f}"
    elements.append(Paragraph(summary_text, styles['BodyText2']))

    # Build PDF
    doc.build(elements, onFirstPage=_add_footer, onLaterPages=_add_footer)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================
# REPORT 2: SITE WEEKLY REPORT
# ============================================

def generate_site_weekly_pdf(
    tenant_name: str,
    site_name: str,
    site_address: str,
    week_start: date,
    week_end: date,
    timesheet_entries: List[Dict[str, Any]],
    site_updates: List[Dict[str, Any]],
    users: Dict[str, str],
    work_categories: Optional[List[Dict[str, Any]]] = None,
    weather: Optional[Dict[str, Any]] = None,
) -> bytes:
    """
    Generate a site weekly report PDF.

    Args:
        tenant_name: Company name
        site_name: Name of the site
        site_address: Site address
        week_start: Start of report period
        week_end: End of report period
        timesheet_entries: Timesheet entries for this site
        site_updates: Site progress updates for this site
        users: Dict of user_id -> user_name
        work_categories: AI-categorised work items (if available)
        weather: Dict of date_str -> weather data (from get_weather_for_site)
    """
    buffer = io.BytesIO()
    styles = get_styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15*mm,
        rightMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=20*mm,
    )

    elements = []

    # Header
    period_label = f"Week: {week_start.strftime('%d %b %Y')} - {week_end.strftime('%d %b %Y')}"
    elements.extend(_build_header(tenant_name, f"Site Report: {site_name}", period_label, styles))

    if site_address:
        elements.append(Paragraph(f"<b>Address:</b> {site_address}", styles['BodyText2']))
        elements.append(Spacer(1, 3*mm))

    # ---- WEATHER STRIP ----
    if weather:
        from datetime import timedelta as td
        weather_location = ""
        meta = weather.get("_meta")
        if isinstance(meta, dict):
            weather_location = meta.get("location", "")

        heading_text = "Weather"
        if weather_location:
            heading_text += f"  <font size='7' color='#999999'>(Based on {weather_location})</font>"
        elements.append(Paragraph(heading_text, styles['SectionHeading']))

        # Build weather table: one column per day
        w_days = []
        current = week_start
        while current <= week_end:
            w_days.append(current)
            current += td(days=1)

        from app.admin.pdf_weather_icons import get_weather_icon

        _center_sm = ParagraphStyle('CenterSm', parent=styles['SmallGrey'], alignment=TA_CENTER, fontSize=7, leading=9)
        _center_temp = ParagraphStyle('CenterTemp', parent=styles['SmallGrey'], alignment=TA_CENTER, fontSize=9, leading=11)
        _center_rain = ParagraphStyle('CenterRain', parent=styles['SmallGrey'], alignment=TA_CENTER, fontSize=7, leading=9, textColor=colors.HexColor("#3B82F6"))

        header = [Paragraph(f"<b>{d.strftime('%a')}</b><br/>{d.strftime('%d %b')}", _center_sm) for d in w_days]
        icon_row = []
        condition_row = []
        temps_row = []
        rain_row = []

        for d in w_days:
            ds = d.isoformat()
            w = weather.get(ds, {})
            if isinstance(w, dict) and w.get("temperature_max") is not None:
                icon_key = w.get("weather_icon", "cloud")
                icon_row.append(get_weather_icon(icon_key, size=28))

                desc = w.get("weather_description", "")
                condition_row.append(Paragraph(desc, _center_sm))

                t_max = round(w.get("temperature_max", 0))
                t_min = round(w.get("temperature_min", 0))
                temps_row.append(Paragraph(f"<b>{t_max}</b>/{t_min} \u00B0C", _center_temp))

                precip = w.get("precipitation_mm", 0)
                if precip and precip > 0:
                    rain_row.append(Paragraph(f"{precip:.1f}mm", _center_rain))
                else:
                    rain_row.append(Paragraph("-", _center_sm))
            else:
                icon_row.append(Paragraph("-", _center_sm))
                condition_row.append(Paragraph("-", _center_sm))
                temps_row.append(Paragraph("", _center_sm))
                rain_row.append(Paragraph("", _center_sm))

        page_width = A4[0] - 30*mm
        col_w = page_width / len(w_days)
        w_widths = [col_w] * len(w_days)

        w_table = Table([header, icon_row, condition_row, temps_row, rain_row], colWidths=w_widths)

        # Highlight rainy days
        style_cmds = [
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E8E8F0")),
            ('BACKGROUND', (0, 1), (-1, -1), LIGHT_GREY),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, WHITE),
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, MID_GREY),
        ]
        for i, d in enumerate(w_days):
            ds = d.isoformat()
            w = weather.get(ds, {})
            if isinstance(w, dict):
                precip = w.get("precipitation_mm", 0)
                if precip and precip >= 5:
                    style_cmds.append(('BACKGROUND', (i, 1), (i, -1), colors.HexColor("#DBEAFE")))
                elif precip and precip > 0:
                    style_cmds.append(('BACKGROUND', (i, 1), (i, -1), colors.HexColor("#EFF6FF")))

        w_table.setStyle(TableStyle(style_cmds))
        elements.append(w_table)
        elements.append(Spacer(1, 3*mm))

    # ---- SECTION 1: Hours Summary ----
    elements.append(Paragraph("Hours Summary", styles['SectionHeading']))

    from datetime import timedelta
    days = []
    current = week_start
    while current <= week_end:
        days.append(current)
        current += timedelta(days=1)

    # Group by user
    user_hours = {}
    for entry in timesheet_entries:
        uid = entry.get("user_id")
        work_date_str = entry.get("work_date")
        hours = float(entry.get("hours_worked", 0))
        if uid not in user_hours:
            user_hours[uid] = {}
        user_hours[uid][work_date_str] = user_hours[uid].get(work_date_str, 0) + hours

    sorted_users = sorted(user_hours.keys(), key=lambda uid: users.get(uid, "Unknown"))

    def _initials(name):
        parts = name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        elif parts:
            return parts[0][0].upper()
        return "?"

    if sorted_users:
        day_labels = [d.strftime("%a\n%d") for d in days]
        header_row = ["Name"] + day_labels + ["Total"]
        table_data = [header_row]

        for uid in sorted_users:
            name = users.get(uid, "Unknown")
            row = [f"[{_initials(name)}]  {name}"]
            total = 0
            for d in days:
                ds = d.strftime("%Y-%m-%d")
                h = user_hours[uid].get(ds, 0)
                total += h
                row.append(_format_hours(h))
            row.append(f"{total:.1f}")
            table_data.append(row)

        # Totals
        totals_row = ["TOTAL"]
        grand = 0
        for d in days:
            ds = d.strftime("%Y-%m-%d")
            dt = sum(user_hours[uid].get(ds, 0) for uid in sorted_users)
            grand += dt
            totals_row.append(f"{dt:.1f}")
        totals_row.append(f"{grand:.1f}")
        table_data.append(totals_row)

        page_width = A4[0] - 30*mm
        name_w = 35*mm
        col_w = (page_width - name_w) / (len(header_row) - 1)
        col_widths = [name_w] + [col_w] * (len(header_row) - 1)

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), LIGHT_GREY),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (-1, 1), (-1, -2), LIGHT_GREY),
            ('FONTNAME', (-1, 1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
            ('LINEBELOW', (0, 0), (-1, 0), 1, NAVY),
            ('LINEABOVE', (0, -1), (-1, -1), 1, NAVY),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(
            f"<b>Total Workers:</b> {len(sorted_users)}  |  <b>Total Hours:</b> {grand:.1f}",
            styles['SmallGrey']
        ))
    else:
        elements.append(Paragraph("No timesheet entries recorded this week.", styles['BodyText2']))

    # ---- SECTION 2: Work Completed ----
    elements.append(Paragraph("Work Completed", styles['SectionHeading']))

    if work_categories:
        # Use AI-categorised work items
        for cat in work_categories:
            cat_name = cat.get("name", "General")
            items = cat.get("items", [])
            if not items:
                continue
            elements.append(Paragraph(cat_name.upper(), styles['SubSectionHeading']))
            for item in items:
                text = item.get("text", "")
                workers = item.get("workers", [])
                worker_str = ""
                if workers:
                    worker_str = f"  <font color='#3B82F6'><b>[{', '.join(workers)}]</b></font>"
                elements.append(Paragraph(f"\u2022 {text}{worker_str}", styles['BulletItem']))
    else:
        # Fallback: raw work items
        work_items = []
        for entry in timesheet_entries:
            desc = entry.get("work_description", "")
            if desc and desc.strip():
                user_name = users.get(entry.get("user_id"), "Unknown")
                work_items.append(f"{desc.strip()} <font color='#999999'>({user_name})</font>")

        for update in site_updates:
            progress = update.get("work_progress", "")
            if progress and progress.strip():
                work_items.append(progress.strip())
            focus = update.get("main_focus", "")
            if focus and focus.strip():
                work_items.append(focus.strip())

        if work_items:
            for item in work_items:
                elements.append(Paragraph(f"\u2022 {item}", styles['BulletItem']))
        else:
            elements.append(Paragraph("No work descriptions recorded this week.", styles['BodyText2']))

    # ---- SECTION 3: Risks / Issues / Escalations ----
    elements.append(Paragraph("Risks, Issues & Escalations", styles['SectionHeading']))

    risk_items = []
    for update in site_updates:
        if update.get("has_urgent_issues") or update.get("has_delays") or update.get("has_safety_concerns"):
            issues = update.get("issues", "")
            delays = update.get("delays", "")
            if issues and issues.strip():
                risk_items.append(f"<b>Issue:</b> {issues.strip()}")
            if delays and delays.strip():
                risk_items.append(f"<b>Delay:</b> {delays.strip()}")

        # Check blockers JSON
        blockers = update.get("identified_blockers") or []
        for b in blockers:
            if isinstance(b, dict):
                risk_items.append(f"<b>{b.get('blocker_type', 'Blocker')}:</b> {b.get('description', '')}")

        # Check concerns JSON
        concerns = update.get("flagged_concerns") or []
        for c in concerns:
            if isinstance(c, dict):
                sev = c.get("severity", "")
                desc = c.get("description", "")
                risk_items.append(f"<b>{sev.title() if sev else 'Concern'}:</b> {desc}")

    if risk_items:
        for item in risk_items:
            elements.append(Paragraph(f"\u26a0 {item}", styles['RiskItem']))
    else:
        elements.append(Paragraph("No risks or issues flagged this week.", styles['BodyText2']))

    # ---- SECTION 4: Next Week / Follow-ups ----
    elements.append(Paragraph("Plans & Follow-ups", styles['SectionHeading']))

    plans = []
    for entry in timesheet_entries:
        plan = entry.get("plans_for_tomorrow", "")
        if plan and plan.strip():
            plans.append(plan.strip())

    for update in site_updates:
        actions = update.get("follow_up_actions", "")
        if actions and actions.strip():
            plans.append(actions.strip())
        action_items = update.get("extracted_action_items") or []
        for a in action_items:
            if isinstance(a, dict):
                plans.append(f"{a.get('action', '')} (Priority: {a.get('priority', 'normal')})")

    if plans:
        # Deduplicate
        seen = set()
        for p in plans:
            if p not in seen:
                seen.add(p)
                elements.append(Paragraph(f"\u2022 {p}", styles['BulletItem']))
    else:
        elements.append(Paragraph("No follow-up items recorded.", styles['BodyText2']))

    # ---- SECTION 5: Site Conditions ----
    conditions = []
    for update in site_updates:
        cond = update.get("site_conditions", "")
        if cond and cond.strip():
            conditions.append(cond.strip())
        if update.get("is_wet_weather_closure"):
            conditions.append("Wet weather closure recorded")

    if conditions:
        elements.append(Paragraph("Site Conditions", styles['SectionHeading']))
        for c in conditions:
            elements.append(Paragraph(f"\u2022 {c}", styles['BulletItem']))

    # Build PDF
    doc.build(elements, onFirstPage=_add_footer, onLaterPages=_add_footer)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================
# REPORT 3: SITE PROGRESS REPORT (Long Duration)
# ============================================

def generate_site_progress_pdf(
    tenant_name: str,
    site_name: str,
    site_address: str,
    period_start: date,
    period_end: date,
    weeks_data: List[Dict[str, Any]],
    flavour: str = "client",  # "client" or "internal"
) -> bytes:
    """
    Generate a site progress report PDF (multi-week).

    Args:
        tenant_name: Company name
        site_name: Name of the site
        site_address: Site address
        period_start: Start of report period
        period_end: End of report period
        weeks_data: List of weekly summaries, each containing:
            - week_start, week_end
            - total_hours, worker_count
            - work_summary (text)
            - risks (list, internal only)
            - conditions (text)
            - plans (text)
        flavour: "client" (progress only) or "internal" (full detail)
    """
    buffer = io.BytesIO()
    styles = get_styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15*mm,
        rightMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=20*mm,
    )

    elements = []

    # Header
    period_label = f"{period_start.strftime('%d %b %Y')} - {period_end.strftime('%d %b %Y')}"
    report_type = "Site Progress Report" if flavour == "client" else "Site Progress Report (Internal)"
    elements.extend(_build_header(tenant_name, report_type, period_label, styles))

    elements.append(Paragraph(f"<b>Site:</b> {site_name}", styles['BodyText2']))
    if site_address:
        elements.append(Paragraph(f"<b>Address:</b> {site_address}", styles['BodyText2']))
    elements.append(Spacer(1, 4*mm))

    # ---- Overview table (hours per week) ----
    elements.append(Paragraph("Weekly Overview", styles['SectionHeading']))

    overview_header = ["Week", "Hours", "Workers"]
    if flavour == "internal":
        overview_header.append("Issues")

    overview_data = [overview_header]
    total_hours = 0
    for week in weeks_data:
        ws = week.get("week_start")
        we = week.get("week_end")
        label = f"{ws.strftime('%d %b')} - {we.strftime('%d %b')}" if isinstance(ws, date) else str(ws)
        hours = week.get("total_hours", 0)
        total_hours += hours
        workers = week.get("worker_count", 0)
        row = [label, _format_hours(hours), str(workers)]
        if flavour == "internal":
            risk_count = len(week.get("risks", []))
            row.append(str(risk_count) if risk_count > 0 else "-")
        overview_data.append(row)

    # Totals
    totals = ["TOTAL", f"{total_hours:.1f}", ""]
    if flavour == "internal":
        totals.append("")
    overview_data.append(totals)

    page_width = A4[0] - 30*mm
    ov_widths = [50*mm, 25*mm, 25*mm]
    if flavour == "internal":
        ov_widths.append(25*mm)

    overview_table = Table(overview_data, colWidths=ov_widths, repeatRows=1)
    overview_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BACKGROUND', (0, -1), (-1, -1), LIGHT_GREY),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('LINEBELOW', (0, 0), (-1, 0), 1, NAVY),
        ('LINEABOVE', (0, -1), (-1, -1), 1, NAVY),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(overview_table)
    elements.append(Spacer(1, 4*mm))

    # ---- Week-by-week detail ----
    elements.append(Paragraph("Week-by-Week Detail", styles['SectionHeading']))

    for week in weeks_data:
        ws = week.get("week_start")
        we = week.get("week_end")
        label = f"{ws.strftime('%d %b')} - {we.strftime('%d %b %Y')}" if isinstance(ws, date) else str(ws)

        week_elements = []
        week_elements.append(Paragraph(f"Week of {label}", styles['SubSectionHeading']))

        hours = week.get("total_hours", 0)
        workers = week.get("worker_count", 0)
        week_elements.append(Paragraph(
            f"<b>Hours:</b> {hours:.1f}  |  <b>Workers:</b> {workers}",
            styles['SmallGrey']
        ))

        # Compact weather strip for this week
        week_weather = week.get("weather", [])
        if week_weather:
            weather_parts = []
            for dw in week_weather:
                rain = dw.get("rain_mm", 0)
                temp = dw.get("temp_max", "")
                day_label = dw.get("day_label", "")
                desc = dw.get("description", "")
                # Short label like "Mon 28° Rain 3.1mm" or "Tue 22° Overcast"
                part = f"<b>{day_label}</b> {temp}\u00B0 {desc}"
                if rain and rain > 0:
                    part += f" <font color='#3B82F6'>{rain}mm</font>"
                weather_parts.append(part)
            weather_line = "  |  ".join(weather_parts)
            week_elements.append(Paragraph(weather_line, styles['SmallGrey']))

        # Work summary
        if flavour == "internal":
            # Categorised work items (same format as Site Weekly)
            work_cats = week.get("work_categories", [])
            if work_cats:
                week_elements.append(Spacer(1, 2*mm))
                for cat in work_cats:
                    cat_name = cat.get("name", "General")
                    items = cat.get("items", [])
                    if not items:
                        continue
                    week_elements.append(Paragraph(
                        f"<b>{cat_name.upper()}</b>",
                        ParagraphStyle('ProgCatHead', parent=styles['SmallGrey'], fontSize=7, textColor=ACCENT_BLUE, spaceBefore=2*mm)
                    ))
                    for item in items:
                        text = item.get("text", "")
                        workers = item.get("workers", [])
                        worker_str = ""
                        if workers:
                            worker_str = f"  <font color='#3B82F6'><b>[{', '.join(workers)}]</b></font>"
                        week_elements.append(Paragraph(f"\u2022 {text}{worker_str}", styles['BulletItem']))
            else:
                work_summary = week.get("work_summary", "")
                if work_summary:
                    week_elements.append(Spacer(1, 2*mm))
                    week_elements.append(Paragraph(work_summary, styles['BodyText2']))
        else:
            # Client view: flat summary
            work_summary = week.get("work_summary", "")
            if work_summary:
                week_elements.append(Spacer(1, 2*mm))
                week_elements.append(Paragraph(work_summary, styles['BodyText2']))

        # Internal only: risks and conditions
        if flavour == "internal":
            risks = week.get("risks", [])
            if risks:
                week_elements.append(Spacer(1, 2*mm))
                week_elements.append(Paragraph("<b>Risks & Issues:</b>", styles['BodyText2']))
                for r in risks:
                    week_elements.append(Paragraph(f"\u26a0 {r}", styles['RiskItem']))

            conditions = week.get("conditions", "")
            if conditions:
                week_elements.append(Spacer(1, 2*mm))
                week_elements.append(Paragraph(f"<b>Site Conditions:</b> {conditions}", styles['BodyText2']))

            plans = week.get("plans", "")
            if plans:
                week_elements.append(Spacer(1, 2*mm))
                week_elements.append(Paragraph(f"<b>Plans/Follow-ups:</b> {plans}", styles['BodyText2']))

        week_elements.append(HRFlowable(
            width="100%", thickness=0.5, color=MID_GREY,
            spaceAfter=2*mm, spaceBefore=2*mm
        ))

        elements.append(KeepTogether(week_elements))

    # Build PDF
    doc.build(elements, onFirstPage=_add_footer, onLaterPages=_add_footer)
    buffer.seek(0)
    return buffer.getvalue()
