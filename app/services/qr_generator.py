"""QR code generation and PDF utilities for site sign-on."""

import io
import secrets
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import os
import logging

logger = logging.getLogger(__name__)


def generate_short_code() -> str:
    """Generate an 8-character URL-safe random short code."""
    return secrets.token_urlsafe(6)  # 6 bytes = 8 base64 chars


def get_signon_url(short_code: str) -> str:
    """Build the full sign-on URL from a short code."""
    base_url = os.getenv("QR_BASE_URL") or os.getenv("PROD_WEBHOOK_BASE_URL", "https://journ3y-vapi-skills-service.up.railway.app")
    return f"{base_url}/s/{short_code}"


def generate_qr_image(url: str, box_size: int = 10, border: int = 4) -> bytes:
    """Generate a QR code PNG image for the given URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


def generate_qr_pdf(site_name: str, site_address: "Optional[str]", qr_url: str) -> bytes:
    """Generate an A4 PDF with QR code, site name, and instructions."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # JOURN3Y branding at top
    logo_path = os.path.join(os.path.dirname(__file__), "..", "admin", "static", "images", "JOURN3Y_SQUARE_PNG.png")
    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, width / 2 - 20 * mm, height - 45 * mm, 40 * mm, 40 * mm, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            logger.warning(f"Could not draw logo: {e}")

    # Site name
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 65 * mm, "Site Sign-On")

    c.setFont("Helvetica-Bold", 22)
    # Truncate long site names
    display_name = site_name if len(site_name) <= 40 else site_name[:37] + "..."
    c.drawCentredString(width / 2, height - 80 * mm, display_name)

    if site_address:
        c.setFont("Helvetica", 14)
        display_addr = site_address if len(site_address) <= 60 else site_address[:57] + "..."
        c.drawCentredString(width / 2, height - 90 * mm, display_addr)

    # QR code - large and centered
    qr_bytes = generate_qr_image(qr_url, box_size=12, border=4)
    qr_image = ImageReader(io.BytesIO(qr_bytes))
    qr_size = 120 * mm
    c.drawImage(qr_image, width / 2 - qr_size / 2, height - 95 * mm - qr_size, qr_size, qr_size)

    # Instructions
    instruction_y = height - 100 * mm - qr_size - 10 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, instruction_y, "Scan this QR code with your phone camera")

    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, instruction_y - 20, "to sign on when you arrive at this site.")

    # Footer
    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width / 2, 20 * mm, "Powered by JOURN3Y")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()
