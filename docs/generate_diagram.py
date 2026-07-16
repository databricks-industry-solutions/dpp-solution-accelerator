"""
DPP Solution Accelerator Architecture Diagram
Pure Python stdlib PNG generator (no external deps)
"""

import struct
import zlib
import math
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal PNG writer
# ---------------------------------------------------------------------------

def _chunk(tag: bytes, data: bytes) -> bytes:
    c = tag + data
    crc = zlib.crc32(c) & 0xFFFFFFFF
    return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)


def write_png(path: str, pixels: list, width: int, height: int):
    """Write an RGB pixel array as a PNG file."""
    raw = b''
    for row in pixels:
        raw += b'\x00'
        for r, g, b in row:
            raw += bytes([r, g, b])
    compressed = zlib.compress(raw, 9)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    png = sig + _chunk(b'IHDR', ihdr_data) + _chunk(b'IDAT', compressed) + _chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def new_canvas(w: int, h: int, bg=(255, 255, 255)) -> list:
    return [[list(bg) for _ in range(w)] for _ in range(h)]


def clamp(v, lo=0, hi=255):
    return max(lo, min(hi, int(v)))


def put_pixel(canvas, x, y, color):
    h = len(canvas)
    w = len(canvas[0])
    if 0 <= y < h and 0 <= x < w:
        canvas[y][x] = [clamp(color[0]), clamp(color[1]), clamp(color[2])]


def blend(canvas, x, y, color, alpha=1.0):
    """Alpha-blend a color onto canvas."""
    h = len(canvas)
    w = len(canvas[0])
    if 0 <= y < h and 0 <= x < w:
        bg = canvas[y][x]
        r = int(bg[0] * (1 - alpha) + color[0] * alpha)
        g = int(bg[1] * (1 - alpha) + color[1] * alpha)
        b = int(bg[2] * (1 - alpha) + color[2] * alpha)
        canvas[y][x] = [clamp(r), clamp(g), clamp(b)]


def draw_hline(canvas, x1, x2, y, color, thickness=1):
    for dy in range(thickness):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            put_pixel(canvas, x, y + dy, color)


def draw_vline(canvas, x, y1, y2, color, thickness=1):
    for dx in range(thickness):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            put_pixel(canvas, x + dx, y, color)


def draw_rect(canvas, x, y, w, h, color, thickness=1):
    draw_hline(canvas, x, x + w, y, color, thickness)
    draw_hline(canvas, x, x + w, y + h, color, thickness)
    draw_vline(canvas, x, y, y + h, color, thickness)
    draw_vline(canvas, x + w, y, y + h, color, thickness)


def fill_rect(canvas, x, y, w, h, color):
    for dy in range(h + 1):
        for dx in range(w + 1):
            put_pixel(canvas, x + dx, y + dy, color)


def fill_rect_gradient(canvas, x, y, w, h, color_top, color_bot):
    """Vertical gradient fill."""
    for dy in range(h + 1):
        t = dy / max(h, 1)
        r = int(color_top[0] * (1 - t) + color_bot[0] * t)
        g = int(color_top[1] * (1 - t) + color_bot[1] * t)
        b_c = int(color_top[2] * (1 - t) + color_bot[2] * t)
        for dx in range(w + 1):
            put_pixel(canvas, x + dx, y + dy, (r, g, b_c))


def rounded_rect_fill(canvas, x, y, w, h, color, r=8):
    """Approximate rounded rectangle fill."""
    # Fill center strip
    fill_rect(canvas, x + r, y, w - 2 * r, h, color)
    fill_rect(canvas, x, y + r, w, h - 2 * r, color)
    # Four corner circles
    for cx, cy in [(x + r, y + r), (x + w - r, y + r),
                   (x + r, y + h - r), (x + w - r, y + h - r)]:
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    put_pixel(canvas, cx + dx, cy + dy, color)


def rounded_rect_stroke(canvas, x, y, w, h, color, r=8, thickness=2):
    """Draw rounded rectangle border."""
    # Straight edges
    draw_hline(canvas, x + r, x + w - r, y, color, thickness)
    draw_hline(canvas, x + r, x + w - r, y + h, color, thickness)
    draw_vline(canvas, x, y + r, y + h - r, color, thickness)
    draw_vline(canvas, x + w, y + r, y + h - r, color, thickness)
    # Corner arcs (Bresenham)
    corners = [
        (x + r, y + r, -1, -1),
        (x + w - r, y + r, 1, -1),
        (x + r, y + h - r, -1, 1),
        (x + w - r, y + h - r, 1, 1),
    ]
    for cx, cy, sx, sy in corners:
        for angle_deg in range(0, 91):
            ang = math.radians(angle_deg)
            px = int(cx + sx * r * math.cos(ang))
            py = int(cy + sy * r * math.sin(ang))
            for t in range(thickness):
                put_pixel(canvas, px + t, py, color)
                put_pixel(canvas, px, py + t, color)


def draw_line(canvas, x1, y1, x2, y2, color, thickness=2):
    """Bresenham line with thickness."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    cx, cy = x1, y1
    while True:
        for t in range(thickness):
            put_pixel(canvas, cx + t, cy, color)
            put_pixel(canvas, cx, cy + t, color)
        if cx == x2 and cy == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy


def draw_arrow(canvas, x1, y1, x2, y2, color, thickness=2, head=8):
    """Draw arrow from (x1,y1) to (x2,y2)."""
    draw_line(canvas, x1, y1, x2, y2, color, thickness)
    # Arrowhead
    ang = math.atan2(y2 - y1, x2 - x1)
    for side in [0.5, -0.5]:
        ax = int(x2 - head * math.cos(ang - side))
        ay = int(y2 - head * math.sin(ang - side))
        draw_line(canvas, x2, y2, ax, ay, color, thickness)


def draw_dashed_line(canvas, x1, y1, x2, y2, color, thickness=2, dash=10, gap=6):
    """Dashed line."""
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return
    dx = (x2 - x1) / length
    dy = (y2 - y1) / length
    pos = 0
    drawing = True
    while pos < length:
        seg = dash if drawing else gap
        end = min(pos + seg, length)
        if drawing:
            ex = int(x1 + dx * end)
            ey = int(y1 + dy * end)
            sx2 = int(x1 + dx * pos)
            sy2 = int(y1 + dy * pos)
            draw_line(canvas, sx2, sy2, ex, ey, color, thickness)
        pos = end
        drawing = not drawing


def draw_dashed_arrow(canvas, x1, y1, x2, y2, color, thickness=2):
    draw_dashed_line(canvas, x1, y1, x2, y2, color, thickness)
    ang = math.atan2(y2 - y1, x2 - x1)
    head = 8
    for side in [0.5, -0.5]:
        ax = int(x2 - head * math.cos(ang - side))
        ay = int(y2 - head * math.sin(ang - side))
        draw_line(canvas, x2, y2, ax, ay, color, thickness)


# ---------------------------------------------------------------------------
# Font: 5x7 bitmap (printable ASCII 32-126)
# ---------------------------------------------------------------------------

FONT_W, FONT_H = 5, 7

FONT = {
    ' ': [0x00,0x00,0x00,0x00,0x00],
    '!': [0x00,0x5F,0x00,0x00,0x00],
    '"': [0x07,0x00,0x07,0x00,0x00],
    '#': [0x14,0x7F,0x14,0x7F,0x14],
    '$': [0x24,0x2A,0x7F,0x2A,0x12],
    '%': [0x23,0x13,0x08,0x64,0x62],
    '&': [0x36,0x49,0x55,0x22,0x50],
    "'": [0x00,0x05,0x03,0x00,0x00],
    '(': [0x00,0x1C,0x22,0x41,0x00],
    ')': [0x00,0x41,0x22,0x1C,0x00],
    '*': [0x14,0x08,0x3E,0x08,0x14],
    '+': [0x08,0x08,0x3E,0x08,0x08],
    ',': [0x00,0x50,0x30,0x00,0x00],
    '-': [0x08,0x08,0x08,0x08,0x08],
    '.': [0x00,0x60,0x60,0x00,0x00],
    '/': [0x20,0x10,0x08,0x04,0x02],
    '0': [0x3E,0x51,0x49,0x45,0x3E],
    '1': [0x00,0x42,0x7F,0x40,0x00],
    '2': [0x42,0x61,0x51,0x49,0x46],
    '3': [0x21,0x41,0x45,0x4B,0x31],
    '4': [0x18,0x14,0x12,0x7F,0x10],
    '5': [0x27,0x45,0x45,0x45,0x39],
    '6': [0x3C,0x4A,0x49,0x49,0x30],
    '7': [0x01,0x71,0x09,0x05,0x03],
    '8': [0x36,0x49,0x49,0x49,0x36],
    '9': [0x06,0x49,0x49,0x29,0x1E],
    ':': [0x00,0x36,0x36,0x00,0x00],
    ';': [0x00,0x56,0x36,0x00,0x00],
    '<': [0x08,0x14,0x22,0x41,0x00],
    '=': [0x14,0x14,0x14,0x14,0x14],
    '>': [0x00,0x41,0x22,0x14,0x08],
    '?': [0x02,0x01,0x51,0x09,0x06],
    '@': [0x32,0x49,0x79,0x41,0x3E],
    'A': [0x7E,0x11,0x11,0x11,0x7E],
    'B': [0x7F,0x49,0x49,0x49,0x36],
    'C': [0x3E,0x41,0x41,0x41,0x22],
    'D': [0x7F,0x41,0x41,0x22,0x1C],
    'E': [0x7F,0x49,0x49,0x49,0x41],
    'F': [0x7F,0x09,0x09,0x09,0x01],
    'G': [0x3E,0x41,0x49,0x49,0x7A],
    'H': [0x7F,0x08,0x08,0x08,0x7F],
    'I': [0x00,0x41,0x7F,0x41,0x00],
    'J': [0x20,0x40,0x41,0x3F,0x01],
    'K': [0x7F,0x08,0x14,0x22,0x41],
    'L': [0x7F,0x40,0x40,0x40,0x40],
    'M': [0x7F,0x02,0x0C,0x02,0x7F],
    'N': [0x7F,0x04,0x08,0x10,0x7F],
    'O': [0x3E,0x41,0x41,0x41,0x3E],
    'P': [0x7F,0x09,0x09,0x09,0x06],
    'Q': [0x3E,0x41,0x51,0x21,0x5E],
    'R': [0x7F,0x09,0x19,0x29,0x46],
    'S': [0x46,0x49,0x49,0x49,0x31],
    'T': [0x01,0x01,0x7F,0x01,0x01],
    'U': [0x3F,0x40,0x40,0x40,0x3F],
    'V': [0x1F,0x20,0x40,0x20,0x1F],
    'W': [0x3F,0x40,0x38,0x40,0x3F],
    'X': [0x63,0x14,0x08,0x14,0x63],
    'Y': [0x07,0x08,0x70,0x08,0x07],
    'Z': [0x61,0x51,0x49,0x45,0x43],
    '[': [0x00,0x7F,0x41,0x41,0x00],
    '\\': [0x02,0x04,0x08,0x10,0x20],
    ']': [0x00,0x41,0x41,0x7F,0x00],
    '^': [0x04,0x02,0x01,0x02,0x04],
    '_': [0x40,0x40,0x40,0x40,0x40],
    '`': [0x00,0x01,0x02,0x04,0x00],
    'a': [0x20,0x54,0x54,0x54,0x78],
    'b': [0x7F,0x48,0x44,0x44,0x38],
    'c': [0x38,0x44,0x44,0x44,0x20],
    'd': [0x38,0x44,0x44,0x48,0x7F],
    'e': [0x38,0x54,0x54,0x54,0x18],
    'f': [0x08,0x7E,0x09,0x01,0x02],
    'g': [0x0C,0x52,0x52,0x52,0x3E],
    'h': [0x7F,0x08,0x04,0x04,0x78],
    'i': [0x00,0x44,0x7D,0x40,0x00],
    'j': [0x20,0x40,0x44,0x3D,0x00],
    'k': [0x7F,0x10,0x28,0x44,0x00],
    'l': [0x00,0x41,0x7F,0x40,0x00],
    'm': [0x7C,0x04,0x18,0x04,0x78],
    'n': [0x7C,0x08,0x04,0x04,0x78],
    'o': [0x38,0x44,0x44,0x44,0x38],
    'p': [0x7C,0x14,0x14,0x14,0x08],
    'q': [0x08,0x14,0x14,0x18,0x7C],
    'r': [0x7C,0x08,0x04,0x04,0x08],
    's': [0x48,0x54,0x54,0x54,0x20],
    't': [0x04,0x3F,0x44,0x40,0x20],
    'u': [0x3C,0x40,0x40,0x20,0x7C],
    'v': [0x1C,0x20,0x40,0x20,0x1C],
    'w': [0x3C,0x40,0x30,0x40,0x3C],
    'x': [0x44,0x28,0x10,0x28,0x44],
    'y': [0x0C,0x50,0x50,0x50,0x3C],
    'z': [0x44,0x64,0x54,0x4C,0x44],
    '{': [0x00,0x08,0x36,0x41,0x00],
    '|': [0x00,0x00,0x7F,0x00,0x00],
    '}': [0x00,0x41,0x36,0x08,0x00],
    '~': [0x08,0x04,0x08,0x10,0x08],
}


def draw_char(canvas, x, y, ch, color, scale=1):
    cols = FONT.get(ch, FONT.get('?', [0]*5))
    for col_i, col_bits in enumerate(cols):
        for row_i in range(7):
            if col_bits & (1 << row_i):
                for sy in range(scale):
                    for sx in range(scale):
                        put_pixel(canvas,
                                  x + col_i * scale + sx,
                                  y + row_i * scale + sy,
                                  color)


def text_width(text, scale=1):
    return len(text) * (FONT_W + 1) * scale


def draw_text(canvas, x, y, text, color, scale=1):
    cx = x
    for ch in text:
        draw_char(canvas, cx, y, ch, color, scale)
        cx += (FONT_W + 1) * scale


def draw_text_centered(canvas, cx, cy, text, color, scale=1):
    tw = text_width(text, scale)
    th = FONT_H * scale
    draw_text(canvas, cx - tw // 2, cy - th // 2, text, color, scale)


def draw_text_multiline(canvas, cx, y, lines, color, scale=1, line_spacing=None):
    if line_spacing is None:
        line_spacing = (FONT_H + 2) * scale
    total_h = len(lines) * line_spacing
    start_y = y - total_h // 2
    for i, line in enumerate(lines):
        tw = text_width(line, scale)
        draw_text(canvas, cx - tw // 2, start_y + i * line_spacing, line, color, scale)


# ---------------------------------------------------------------------------
# High-level layout constants
# ---------------------------------------------------------------------------

W = 1600
H = 1120

# Palette
BG          = (245, 247, 250)
WHITE       = (255, 255, 255)
BLACK       = (20,  20,  30)
GRAY_LIGHT  = (210, 215, 225)
GRAY_MED    = (150, 160, 175)

# Layer colors
COL_SOURCE  = (108, 99, 255)   # purple
COL_INGEST  = (52, 152, 219)   # blue
COL_SDP     = (41, 128, 185)   # darker blue
COL_BRONZE  = (180, 100, 40)   # bronze
COL_SILVER  = (120, 130, 145)  # silver
COL_GOLD    = (195, 155, 30)   # gold
COL_DELTA   = (255, 100, 35)   # Databricks orange
COL_LB      = (39, 174, 96)    # green (Lakebase)
COL_MOD1    = (52, 152, 219)   # blue (Passport Viewer)
COL_MOD2    = (155, 89, 182)   # purple (Compliance)
COL_MOD3    = (46, 204, 113)   # green (Supplier Portal)
COL_MOD4    = (231, 76, 60)    # red (AI/ML)
COL_UC      = (243, 156, 18)   # amber (Unity Catalog)
COL_DAB     = (127, 140, 141)  # gray (DABs)
COL_SYNTH   = (26, 188, 156)   # teal (Synthetic Data)

COL_FOUND_BG  = (232, 245, 255)   # light blue tint - Foundation
COL_OPT_BG    = (240, 255, 245)   # light green tint - Optional
COL_FOUND_BOR = (52, 152, 219)
COL_OPT_BOR   = (39, 174, 96)

ARROW_COLOR = (80, 90, 110)
ARROW_DASHED = (120, 130, 150)


def lighten(color, factor=0.35):
    return tuple(int(c + (255 - c) * factor) for c in color)


def darken(color, factor=0.2):
    return tuple(int(c * (1 - factor)) for c in color)


# ---------------------------------------------------------------------------
# Draw a labeled box (filled rounded rect + title bar + text lines)
# ---------------------------------------------------------------------------

def draw_box(canvas, x, y, w, h, bg_color, border_color, title,
             lines=None, title_scale=1, text_scale=1, border_w=2, radius=6):
    # Fill
    rounded_rect_fill(canvas, x, y, w, h, bg_color, r=radius)
    # Title bar (top strip)
    bar_h = 18 if title_scale == 1 else 22
    rounded_rect_fill(canvas, x, y, w, bar_h, border_color, r=radius)
    fill_rect(canvas, x, y + radius, w, bar_h - radius, border_color)
    # Title text
    draw_text_centered(canvas, x + w // 2, y + bar_h // 2 + 1, title, WHITE, title_scale)
    # Border
    rounded_rect_stroke(canvas, x, y, w, h, border_color, r=radius, thickness=border_w)
    # Body lines
    if lines:
        line_h = (FONT_H + 3) * text_scale
        body_start = y + bar_h + 8
        for i, ln in enumerate(lines):
            tw = text_width(ln, text_scale)
            lx = x + w // 2 - tw // 2
            draw_text(canvas, lx, body_start + i * line_h, ln, BLACK, text_scale)


def draw_small_box(canvas, x, y, w, h, bg_color, border_color, text_lines, text_scale=1):
    """Simple box without a title bar."""
    rounded_rect_fill(canvas, x, y, w, h, bg_color, r=5)
    rounded_rect_stroke(canvas, x, y, w, h, border_color, r=5, thickness=2)
    line_h = (FONT_H + 3) * text_scale
    total_h = len(text_lines) * line_h
    start_y = y + h // 2 - total_h // 2
    for i, ln in enumerate(text_lines):
        tw = text_width(ln, text_scale)
        draw_text(canvas, x + w // 2 - tw // 2, start_y + i * line_h, ln, BLACK, text_scale)


# ---------------------------------------------------------------------------
# Main diagram
# ---------------------------------------------------------------------------

def draw_diagram():
    # ---------------------------------------------------------------
    # Layout constants (all derived from a single source of truth)
    # ---------------------------------------------------------------
    # Column positions (x)
    SRC_X   = 18    # Data source boxes left edge
    SRC_W   = 230   # Data source box width
    FOUND_X = 265   # Foundation panel left edge
    ING_X   = 275   # Ingestion container left edge
    ING_W   = 350   # Ingestion container width
    SDP_X   = 645   # SDP container left edge
    SDP_W   = 350   # SDP container width
    GAP_X   = 1010  # Gap between Foundation right and Optional left (bus zone)
    OPT_X   = 1055  # Optional Modules panel left edge
    OPT_W   = 490   # Optional Modules panel width
    # Total canvas width: OPT_X + OPT_W + margin = 1055+490+25 = 1570 -> use 1580
    CW = 1580
    # Row positions (y) — everything anchored from TOP_Y
    TOP_Y    = 62   # Top of main content panels
    ING_H    = 510  # Ingestion container height
    SDP_H    = 510  # SDP container height
    STOR_Y   = 592  # Storage band top (relative to TOP_Y => absolute = TOP_Y+STOR_Y)
    STOR_H   = 128  # Storage band height
    UC_H     = 52
    DAB_H    = 44
    # Module 4 is at opt_y + 577 + mod_h = 62 + 577 + 165 = 804 (bottom)
    # DABs must start after max(storage+UC, module4_bottom)
    # storage+UC bottom = TOP_Y+STOR_Y+STOR_H + 10 + UC_H = 62+592+128+10+52 = 844
    # module4_bottom + gap = 804 + 12 = 816
    # So DAB_Y = max(844, 816) + 8 = 852
    UC_Y     = TOP_Y + STOR_Y + STOR_H + 10   # = 852... wait: 62+592+128+10 = 792
    # UC_Y = 792, UC bottom = 792+52 = 844
    DAB_Y    = 852                             # >= both 844 (UC bottom+8) and 816 (mod4)
    FOUND_H  = DAB_Y + DAB_H - TOP_Y + 10     # Foundation panel height
    CH       = DAB_Y + DAB_H + 30             # Canvas height with margin

    # Storage absolute coords
    stor_ax  = ING_X
    stor_ay  = TOP_Y + STOR_Y
    stor_aw  = SDP_X + SDP_W - ING_X  # spans ingestion + sdp columns

    # Optional modules panel
    opt_y    = TOP_Y
    opt_h    = DAB_Y + DAB_H - TOP_Y + 10

    canvas = new_canvas(CW, CH, BG)

    # ===== Background gradient top bar =====
    for y in range(50):
        t = y / 50
        r = int(25  * (1-t) + 245 * t)
        g = int(75  * (1-t) + 247 * t)
        b = int(155 * (1-t) + 250 * t)
        draw_hline(canvas, 0, CW-1, y, (r, g, b), 1)

    # ===== Title =====
    draw_text_centered(canvas, CW // 2, 20, "DPP Solution Accelerator - Architecture",
                       (20, 50, 120), scale=2)
    draw_text_centered(canvas, CW // 2, 40,
                       "Databricks | EU ESPR Compliance | Modular & Pluggable",
                       (80, 90, 130), scale=1)

    # ===== Legend (below title, left-center area) =====
    lx, ly = 265, 46
    draw_text(canvas, lx, ly,    "FOUNDATION (required)", COL_FOUND_BOR, scale=1)
    fill_rect(canvas, lx+205, ly-1, 13, 9, COL_FOUND_BG)
    draw_rect(canvas, lx+205, ly-1, 13, 9, COL_FOUND_BOR)
    draw_text(canvas, lx+225, ly, "= always deployed", BLACK, scale=1)
    draw_text(canvas, lx+480, ly, "OPTIONAL MODULES", COL_OPT_BOR, scale=1)
    fill_rect(canvas, lx+680, ly-1, 13, 9, COL_OPT_BG)
    draw_rect(canvas, lx+680, ly-1, 13, 9, COL_OPT_BOR)
    draw_text(canvas, lx+700, ly, "= pick what you need", BLACK, scale=1)
    draw_text(canvas, lx+960, ly, "-- = pluggable connector", ARROW_DASHED, scale=1)

    # ===================================================================
    # FOUNDATION panel (left block: ingestion + SDP + storage + UC + DABs)
    # ===================================================================
    fx  = FOUND_X
    fy  = TOP_Y
    fw  = SDP_X + SDP_W - FOUND_X + 15
    fh  = FOUND_H

    fill_rect(canvas, fx, fy, fw, fh, COL_FOUND_BG)
    draw_dashed_line(canvas, fx, fy, fx+fw, fy,       COL_FOUND_BOR, thickness=2, dash=12, gap=5)
    draw_dashed_line(canvas, fx+fw, fy, fx+fw, fy+fh, COL_FOUND_BOR, thickness=2, dash=12, gap=5)
    draw_dashed_line(canvas, fx, fy+fh, fx+fw, fy+fh, COL_FOUND_BOR, thickness=2, dash=12, gap=5)
    draw_dashed_line(canvas, fx, fy, fx, fy+fh,       COL_FOUND_BOR, thickness=2, dash=12, gap=5)
    draw_text(canvas, fx+8, fy+4, "FOUNDATION MODULE", COL_FOUND_BOR, scale=1)

    # ===================================================================
    # DATA SOURCES (left column, outside foundation)
    # ===================================================================
    draw_text(canvas, SRC_X + 60, TOP_Y - 14, "DATA SOURCES", darken(COL_SOURCE, 0.1), scale=1)
    sources = [
        (TOP_Y +  5,  "ERP Systems",     ["SAP, Oracle", "Dynamics"]),
        (TOP_Y + 130, "Supplier Portal", ["Certificates", "Material data"]),
        (TOP_Y + 255, "IoT / MES",       ["Sensors", "Exec. systems"]),
        (TOP_Y + 380, "Document Stores", ["PDFs, Compliance", "docs"]),
    ]
    for sy, stitle, slines in sources:
        draw_box(canvas, SRC_X, sy, SRC_W, 95, lighten(COL_SOURCE, 0.70), COL_SOURCE,
                 stitle, slines, title_scale=1, text_scale=1)

    # ===================================================================
    # INGESTION LAYER
    # ===================================================================
    ing_y = TOP_Y + 18
    fill_rect(canvas, ING_X, ing_y, ING_W, ING_H, lighten(COL_INGEST, 0.87))
    draw_rect(canvas, ING_X, ing_y, ING_W, ING_H, COL_INGEST, thickness=2)
    draw_text_centered(canvas, ING_X + ING_W//2, ing_y + 10, "INGESTION LAYER", COL_INGEST, scale=1)

    ingestors = [
        (ing_y + 28,  "Lakeflow Connect",  ["CDC from ERP /", "databases"],         COL_INGEST),
        (ing_y + 150, "Auto Loader",        ["Files, documents,", "cloud storage"],  COL_INGEST),
        (ing_y + 272, "Zerobus Ingest",     ["Real-time IoT /", "MES streaming"],    COL_INGEST),
        (ing_y + 390, "Synthetic Data Gen", ["Demo data,", "no customer data needed"], COL_SYNTH),
    ]
    box_w = ING_W - 24
    for iy, ititle, ilines, icol in ingestors:
        draw_box(canvas, ING_X + 12, iy, box_w, 105,
                 lighten(icol, 0.72), icol, ititle, ilines, text_scale=1)

    # ===================================================================
    # SDP PIPELINE
    # ===================================================================
    sdp_y = TOP_Y + 18
    fill_rect(canvas, SDP_X, sdp_y, SDP_W, SDP_H, lighten(COL_SDP, 0.88))
    draw_rect(canvas, SDP_X, sdp_y, SDP_W, SDP_H, COL_SDP, thickness=2)
    draw_text_centered(canvas, SDP_X + SDP_W//2, sdp_y + 10,
                       "SPARK DECLARATIVE PIPELINES (SDP)", COL_SDP, scale=1)

    sdp_box_w = SDP_W - 24
    layers = [
        (sdp_y + 28,  "BRONZE", COL_BRONZE,
         ["Raw ingestion", "Streaming Tables", "Schema-on-read"]),
        (sdp_y + 185, "SILVER", COL_SILVER,
         ["Cleansed & conformed", "Materialized Views", "DQ checks applied"]),
        (sdp_y + 342, "GOLD",   COL_GOLD,
         ["Compliance scores", "LCA metrics", "Material traceability"]),
    ]
    for ly2, lname, lcol, llines in layers:
        draw_box(canvas, SDP_X + 12, ly2, sdp_box_w, 128,
                 lighten(lcol, 0.72), lcol, lname, llines, title_scale=1, text_scale=1)

    # ===================================================================
    # STORAGE - DUAL ENGINE
    # ===================================================================
    stor_y2 = TOP_Y + STOR_Y  # absolute
    stor_w2 = SDP_X + SDP_W - ING_X + 3

    fill_rect(canvas, stor_ax, stor_y2, stor_w2, STOR_H, lighten(COL_DELTA, 0.90))
    draw_rect(canvas, stor_ax, stor_y2, stor_w2, STOR_H, COL_DELTA, thickness=2)
    draw_text_centered(canvas, stor_ax + stor_w2//2, stor_y2 + 10,
                       "STORAGE - DUAL ENGINE", COL_DELTA, scale=1)

    delta_w = (stor_w2 - 36) // 2
    draw_box(canvas, stor_ax + 12, stor_y2 + 24, delta_w, 95,
             lighten(COL_DELTA, 0.70), COL_DELTA,
             "Delta Lake (Unity Catalog)",
             ["Analytical store", "Compliance reporting", "LCA aggregates, lineage"],
             text_scale=1)

    lb_x = stor_ax + 12 + delta_w + 12
    draw_box(canvas, lb_x, stor_y2 + 24, delta_w, 95,
             lighten(COL_LB, 0.70), COL_LB,
             "Lakebase (PostgreSQL)",
             ["Operational store (<100ms)", "QR lookups, supplier entry", "Audit trail"],
             text_scale=1)

    # Bidirectional sync arrows
    mid_gap_x = stor_ax + 12 + delta_w
    sy2 = stor_y2 + 75
    draw_arrow(canvas, mid_gap_x - 2, sy2 - 7, mid_gap_x + 14, sy2 - 7, COL_DELTA, thickness=2, head=7)
    draw_arrow(canvas, mid_gap_x + 14, sy2 + 5, mid_gap_x - 2, sy2 + 5, COL_LB,    thickness=2, head=7)

    # ===================================================================
    # UNITY CATALOG banner
    # ===================================================================
    uc_x = ING_X
    uc_w = stor_w2
    fill_rect(canvas, uc_x, UC_Y, uc_w, UC_H, lighten(COL_UC, 0.75))
    rounded_rect_stroke(canvas, uc_x, UC_Y, uc_w, UC_H, COL_UC, r=6, thickness=2)
    draw_text_centered(canvas, uc_x + uc_w//2, UC_Y + 14, "UNITY CATALOG", COL_UC, scale=2)
    draw_text_centered(canvas, uc_x + uc_w//2, UC_Y + 36,
                       "Governance | Lineage | Access Control | Data Discovery", BLACK, scale=1)

    # ===================================================================
    # ASSET BUNDLES (DABs) footer — spans Foundation + Optional Modules
    # ===================================================================
    dab_x = FOUND_X
    dab_w = OPT_X + OPT_W - FOUND_X
    fill_rect(canvas, dab_x, DAB_Y, dab_w, DAB_H, lighten(COL_DAB, 0.78))
    rounded_rect_stroke(canvas, dab_x, DAB_Y, dab_w, DAB_H, COL_DAB, r=5, thickness=2)
    draw_text_centered(canvas, dab_x + dab_w//2, DAB_Y + 13, "ASSET BUNDLES (DABs)", COL_DAB, scale=2)
    draw_text_centered(canvas, dab_x + dab_w//2, DAB_Y + 31,
                       "Wraps all modules for CI/CD | Each module independently deployable", BLACK, scale=1)

    # ===================================================================
    # OPTIONAL MODULES panel
    # ===================================================================
    fill_rect(canvas, OPT_X, opt_y, OPT_W, opt_h, COL_OPT_BG)
    draw_dashed_line(canvas, OPT_X, opt_y,        OPT_X+OPT_W, opt_y,        COL_OPT_BOR, thickness=2)
    draw_dashed_line(canvas, OPT_X+OPT_W, opt_y,  OPT_X+OPT_W, opt_y+opt_h, COL_OPT_BOR, thickness=2)
    draw_dashed_line(canvas, OPT_X, opt_y+opt_h,  OPT_X+OPT_W, opt_y+opt_h, COL_OPT_BOR, thickness=2)
    draw_dashed_line(canvas, OPT_X, opt_y,         OPT_X,       opt_y+opt_h, COL_OPT_BOR, thickness=2)
    draw_text(canvas, OPT_X + 8, opt_y + 4,
              "OPTIONAL MODULES (Databricks Apps)", COL_OPT_BOR, scale=1)

    mod_w = OPT_W - 28
    mod_h = 165
    # Space 4 modules evenly inside the optional panel height
    # opt_h = FOUND_H = DAB_Y + DAB_H - TOP_Y + 10
    # Modules start 22px from top of panel, end before DABs
    # Available height after header: opt_h - 22 - bottom_pad
    # Use fixed spacing: mod_h=165, gap=20 → 4*(165+20) = 740 → needs opt_h >= 762
    # With TOP_Y=62, FOUND_H dynamically computed: ensure 4 modules fit
    modules = [
        (opt_y + 22,  "Module 1: Passport Viewer",     COL_MOD1,
         ["Consumer QR scan", "Public-facing app", "Databricks Apps"]),
        (opt_y + 207, "Module 2: Compliance Dashboard", COL_MOD2,
         ["AI/BI + Genie Space", "Automated reporting", "ESPR metrics"]),
        (opt_y + 392, "Module 3: Supplier Portal",      COL_MOD3,
         ["Data entry + cert upload", "Certificate validation", "Supplier self-service"]),
        (opt_y + 577, "Module 4: AI/ML Services",       COL_MOD4,
         ["Material classification", "Carbon estimation", "Model Serving endpoint"]),
    ]
    for my, mtitle, mcol, mlines in modules:
        draw_box(canvas, OPT_X + 14, my, mod_w, mod_h,
                 lighten(mcol, 0.75), mcol, mtitle, mlines,
                 title_scale=1, text_scale=1, radius=8)

    # ===================================================================
    # ARROWS
    # ===================================================================

    # -- Data Sources -> Ingestion (dashed = pluggable) --
    src_mid_ys = [sy + 55 for sy, _, _ in sources]
    tgt_mid_ys = [iy + 52 for iy, _, _, _ in ingestors]
    # ERP + Supplier -> Lakeflow Connect
    for src_y_mid in src_mid_ys[:2]:
        draw_dashed_arrow(canvas, SRC_X + SRC_W + 1, src_y_mid,
                          ING_X, tgt_mid_ys[0], ARROW_DASHED, thickness=2)
    # IoT -> Zerobus
    draw_dashed_arrow(canvas, SRC_X + SRC_W + 1, src_mid_ys[2],
                      ING_X, tgt_mid_ys[2], ARROW_DASHED, thickness=2)
    # Docs -> Auto Loader
    draw_dashed_arrow(canvas, SRC_X + SRC_W + 1, src_mid_ys[3],
                      ING_X, tgt_mid_ys[1], ARROW_DASHED, thickness=2)

    # -- Ingestion -> SDP (each ingestor -> Bronze) --
    bronze_mid_y = sdp_y + 28 + 64  # middle of Bronze box
    for iy, _, _, _ in ingestors:
        mid_y = iy + 52
        draw_arrow(canvas, ING_X + ING_W, mid_y, SDP_X, mid_y, ARROW_COLOR, thickness=2)

    # -- SDP Bronze -> Silver -> Gold cascade --
    b_bot = sdp_y + 28 + 128
    s_top = sdp_y + 185
    s_bot = s_top + 128
    g_top = sdp_y + 342
    draw_arrow(canvas, SDP_X + SDP_W//2, b_bot, SDP_X + SDP_W//2, s_top, ARROW_COLOR, thickness=2)
    draw_arrow(canvas, SDP_X + SDP_W//2, s_bot, SDP_X + SDP_W//2, g_top, ARROW_COLOR, thickness=2)

    # -- Gold -> Storage --
    g_bot = sdp_y + 342 + 128
    draw_arrow(canvas, SDP_X + SDP_W//2, g_bot,
               SDP_X + SDP_W//2, stor_y2 + 24, ARROW_COLOR, thickness=2)

    # -- Storage -> Optional Modules via vertical bus in the gap zone --
    # Bus runs vertically from storage mid-right, through the gap, to last module
    bus_x = GAP_X + (OPT_X - GAP_X) // 2  # center of gap zone (~1032)

    # Vertical bus spans from first module mid-y to last module mid-y
    bus_y_top = modules[0][0] + mod_h // 2
    bus_y_bot = modules[-1][0] + mod_h // 2

    # Horizontal stub from storage right edge down to bus at storage mid-height
    stor_mid_y = stor_y2 + STOR_H // 2
    draw_hline(canvas, stor_ax + stor_w2, bus_x, stor_mid_y, ARROW_COLOR, thickness=2)

    # Elbow from storage mid-height down to bus top (first module mid)
    draw_vline(canvas, bus_x, min(stor_mid_y, bus_y_top), max(stor_mid_y, bus_y_top),
               ARROW_COLOR, thickness=2)

    # Vertical bus connecting all module taps
    draw_vline(canvas, bus_x, bus_y_top, bus_y_bot, ARROW_COLOR, thickness=2)

    # Taps: bus -> each module left edge
    for my, _, _, _ in modules:
        mod_mid_y = my + mod_h // 2
        draw_arrow(canvas, bus_x, mod_mid_y, OPT_X + 13, mod_mid_y, ARROW_COLOR, thickness=2)

    # ===================================================================
    # Save
    # ===================================================================
    out_path = str(Path(__file__).resolve().parent / "architecture.png")
    pixels = [[(canvas[y][x][0], canvas[y][x][1], canvas[y][x][2])
               for x in range(CW)] for y in range(CH)]
    write_png(out_path, pixels, CW, CH)
    print(f"Saved: {out_path}  ({CW}x{CH}px)")


if __name__ == "__main__":
    draw_diagram()
