# app/admin/pdf_weather_icons.py - Vector weather icons for PDF reports
import math
from reportlab.graphics.shapes import Drawing, Circle, Line, Polygon, Rect, Group
from reportlab.lib import colors


def _cloud_group(size, color):
    """Reusable cloud shape."""
    g = Group()
    g.add(Circle(size*0.35, size*0.55, size*0.17, fillColor=color, strokeColor=None))
    g.add(Circle(size*0.55, size*0.63, size*0.19, fillColor=color, strokeColor=None))
    g.add(Circle(size*0.7, size*0.55, size*0.14, fillColor=color, strokeColor=None))
    g.add(Rect(size*0.22, size*0.42, size*0.56, size*0.17, fillColor=color, strokeColor=None))
    return g


def icon_sun(size=24):
    d = Drawing(size, size)
    cx, cy, r = size/2, size/2, size*0.22
    d.add(Circle(cx, cy, r, fillColor=colors.HexColor('#F59E0B'), strokeColor=None))
    for i in range(8):
        angle = i * 45 * math.pi / 180
        x1 = cx + (r+2) * math.cos(angle)
        y1 = cy + (r+2) * math.sin(angle)
        x2 = cx + (r+5) * math.cos(angle)
        y2 = cy + (r+5) * math.sin(angle)
        d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor('#F59E0B'), strokeWidth=1.2))
    return d


def icon_cloud_sun(size=24):
    d = Drawing(size, size)
    # Small sun peeking out top-left
    cx, cy, r = size*0.28, size*0.72, size*0.14
    d.add(Circle(cx, cy, r, fillColor=colors.HexColor('#F59E0B'), strokeColor=None))
    for i in range(6):
        angle = i * 60 * math.pi / 180
        x1 = cx + (r+1) * math.cos(angle)
        y1 = cy + (r+1) * math.sin(angle)
        x2 = cx + (r+3.5) * math.cos(angle)
        y2 = cy + (r+3.5) * math.sin(angle)
        d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor('#F59E0B'), strokeWidth=1))
    # Cloud in front
    c = colors.HexColor('#9CA3AF')
    d.add(Circle(size*0.45, size*0.45, size*0.15, fillColor=c, strokeColor=None))
    d.add(Circle(size*0.62, size*0.5, size*0.17, fillColor=c, strokeColor=None))
    d.add(Circle(size*0.75, size*0.43, size*0.12, fillColor=c, strokeColor=None))
    d.add(Rect(size*0.35, size*0.33, size*0.45, size*0.14, fillColor=c, strokeColor=None))
    return d


def icon_cloud(size=24):
    d = Drawing(size, size)
    c = colors.HexColor('#9CA3AF')
    d.add(Circle(size*0.35, size*0.5, size*0.2, fillColor=c, strokeColor=None))
    d.add(Circle(size*0.55, size*0.58, size*0.22, fillColor=c, strokeColor=None))
    d.add(Circle(size*0.72, size*0.5, size*0.16, fillColor=c, strokeColor=None))
    d.add(Rect(size*0.2, size*0.33, size*0.6, size*0.2, fillColor=c, strokeColor=None))
    return d


def icon_fog(size=24):
    d = Drawing(size, size)
    c = colors.HexColor('#9CA3AF')
    for i, y in enumerate([0.65, 0.48, 0.31]):
        w = size * (0.7 - i*0.08)
        x = (size - w) / 2
        d.add(Rect(x, size*y, w, size*0.06, fillColor=c, strokeColor=None, rx=size*0.03))
    return d


def icon_drizzle(size=24):
    d = Drawing(size, size)
    c = colors.HexColor('#6B7280')
    d.add(_cloud_group(size, c))
    # Light drops (dots)
    for x in [size*0.33, size*0.5, size*0.63]:
        d.add(Circle(x, size*0.25, size*0.025, fillColor=colors.HexColor('#3B82F6'), strokeColor=None))
        d.add(Circle(x - 1.5, size*0.15, size*0.025, fillColor=colors.HexColor('#3B82F6'), strokeColor=None))
    return d


def icon_rain(size=24):
    d = Drawing(size, size)
    c = colors.HexColor('#6B7280')
    d.add(_cloud_group(size, c))
    # Rain lines
    blue = colors.HexColor('#3B82F6')
    for x in [size*0.3, size*0.45, size*0.6]:
        d.add(Line(x, size*0.33, x-2, size*0.18, strokeColor=blue, strokeWidth=1.5))
    return d


def icon_snow(size=24):
    d = Drawing(size, size)
    c = colors.HexColor('#6B7280')
    d.add(_cloud_group(size, c))
    # Snowflakes (small asterisks)
    blue = colors.HexColor('#60A5FA')
    for cx in [size*0.3, size*0.5, size*0.65]:
        cy = size*0.22
        r = size*0.05
        for angle in [0, 60, 120]:
            rad = angle * math.pi / 180
            d.add(Line(cx - r*math.cos(rad), cy - r*math.sin(rad),
                       cx + r*math.cos(rad), cy + r*math.sin(rad),
                       strokeColor=blue, strokeWidth=1))
    return d


def icon_storm(size=24):
    d = Drawing(size, size)
    c = colors.HexColor('#4B5563')
    d.add(_cloud_group(size, c))
    # Lightning bolt
    d.add(Polygon(
        [size*0.52, size*0.40,
         size*0.42, size*0.24,
         size*0.50, size*0.24,
         size*0.45, size*0.08,
         size*0.58, size*0.28,
         size*0.50, size*0.28],
        fillColor=colors.HexColor('#F59E0B'), strokeColor=None
    ))
    return d


# Map weather_icon key → drawing function
ICON_BUILDERS = {
    "sun": icon_sun,
    "cloud-sun": icon_cloud_sun,
    "cloud": icon_cloud,
    "fog": icon_fog,
    "cloud-drizzle": icon_drizzle,
    "cloud-rain": icon_rain,
    "cloud-snow": icon_snow,
    "cloud-lightning": icon_storm,
}


def get_weather_icon(icon_key: str, size: int = 24) -> Drawing:
    """Get a vector weather icon Drawing for use in a PDF table cell."""
    builder = ICON_BUILDERS.get(icon_key, icon_cloud)
    return builder(size)
