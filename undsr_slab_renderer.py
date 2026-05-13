#!/usr/bin/env python3
"""
UNDSR Slab Renderer v3 — Composites a card photo into a graded slab image.

Label layout matches the official UNDSR grading scale mockups:
    ┌──────────────────────────────────────────────────┐
    │  🌵     UNDSR                           10       │
    │  cactus THE UNDESIRABLES            PRISTINE     │
    │         CENTERING 10  CORNERS 10                 │
    │         EDGES     10  SURFACE 10                 │
    └──────────────────────────────────────────────────┘

Tiers:
    10      → Pristine   → Holographic rainbow label
    9.5     → Gem Mint   → Gold metallic label
    9.0     → Mint       → Silver brushed label
    8.0-8.5 → Near Mint  → Bronze metallic label
    <8.0    → Standard   → White matte label
"""

import argparse
import os
import sys
import uuid
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False


# ─── UNDSR Brand Constants ───────────────────────────────────────────────────

SLAB_WIDTH = 800
SLAB_HEIGHT = 1200
LABEL_HEIGHT = 160       # Shorter, wider label like the mockups
CARD_PADDING = 40
CARD_AREA_TOP = LABEL_HEIGHT + 20
CARD_AREA_BOTTOM = SLAB_HEIGHT - 70
CORNER_RADIUS = 16

ASSETS_DIR = Path(__file__).parent / "assets"
NOPAL_ICON_PATH = ASSETS_DIR / "nopal_icon.png"

WEBSITE_URL = "https://the-undesirables.com"

# Tier definitions: (min_grade, tier_name, label_bg, label_text_color, accent)
TIERS = [
    (10.0, "PRISTINE",  (218, 165, 32),  (0, 0, 0),       "holo"),
    (9.5,  "GEM MINT",  (205, 173, 55),  (0, 0, 0),       "gold"),
    (9.0,  "MINT",      (169, 169, 175), (0, 0, 0),       "silver"),
    (8.0,  "NEAR MINT", (184, 134, 85),  (0, 0, 0),       "bronze"),
    (0.0,  "STANDARD",  (245, 245, 245), (20, 20, 20),    "white"),
]


def get_tier(grade: float):
    """Return the tier info for a given grade."""
    for min_g, name, bg, text_color, accent in TIERS:
        if grade >= min_g:
            return name, bg, text_color, accent
    return TIERS[-1][1], TIERS[-1][2], TIERS[-1][3], TIERS[-1][4]


def load_nopal_icon(size, color=(0, 0, 0), label_bg=(218, 165, 32)):
    """Load the nopal cactus PNG icon and resize it.
    
    Dark pixels (cactus body) → tinted to `color` (label text color)
    Light pixels (spine dots) → tinted to `label_bg` for contrast
    Transparent pixels → left transparent
    """
    if NOPAL_ICON_PATH.exists():
        icon = Image.open(NOPAL_ICON_PATH).convert("RGBA")
        # Resize preserving aspect ratio to fit within `size` height
        w, h = icon.size
        ratio = size / h
        new_w = int(w * ratio)
        icon = icon.resize((new_w, size), Image.Resampling.LANCZOS)
        
        pixels = icon.load()
        for y in range(icon.height):
            for x in range(icon.width):
                r, g, b, a = pixels[x, y]
                if a < 20:
                    continue
                brightness = (r + g + b) / 3
                if brightness < 120:
                    pixels[x, y] = (color[0], color[1], color[2], a)
                else:
                    pixels[x, y] = (label_bg[0], label_bg[1], label_bg[2], a)
        
        return icon
    return None


def _lerp_color(c1, c2, t):
    """Linearly interpolate between two RGB tuples."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def add_metallic_gradient(img, region, accent):
    """Paint realistic metallic / holographic finish directly onto the label region.
    
    This replaces the flat fill with a gradient that simulates real stamped-metal
    labels like PSA/BGS slabs. Edge darkening + center highlight = 3D depth.
    """
    x1, y1, x2, y2 = region
    width = x2 - x1
    height = y2 - y1
    
    # We paint the gradient directly onto the image (not an overlay)
    pixels = img.load()

    if accent == "holo":
        # Smooth left-to-right pastel rainbow like the mockup
        # Color stops: soft pink → peach → yellow → mint → cyan → lavender → pink
        stops = [
            (220, 180, 220),   # soft lavender-pink
            (240, 200, 180),   # peach
            (240, 230, 160),   # warm yellow
            (180, 230, 170),   # mint green
            (170, 220, 230),   # cyan
            (190, 180, 230),   # lavender
            (220, 180, 210),   # back to pink
        ]
        for x in range(x1, x2):
            # Which segment of the rainbow are we in?
            t_global = (x - x1) / max(1, width - 1)
            seg_f = t_global * (len(stops) - 1)
            seg_i = min(int(seg_f), len(stops) - 2)
            seg_t = seg_f - seg_i
            base_color = _lerp_color(stops[seg_i], stops[seg_i + 1], seg_t)
            
            for y in range(y1, y2):
                # Vertical metallic sheen: brighter at top-center, darker at edges
                vy = (y - y1) / max(1, height - 1)
                # Bell curve brightness centered at ~35% from top
                bright = 1.0 + 0.15 * (1.0 - abs(vy - 0.35) / 0.65)
                # Darken edges slightly
                edge_v = 1.0 - 0.12 * max(0, (vy - 0.85) / 0.15)  # bottom edge
                edge_v *= 1.0 - 0.08 * max(0, (0.05 - vy) / 0.05)  # top edge
                
                r = min(255, int(base_color[0] * bright * edge_v))
                g = min(255, int(base_color[1] * bright * edge_v))
                b = min(255, int(base_color[2] * bright * edge_v))
                pixels[x, y] = (r, g, b, 255)
    
    elif accent == "gold":
        # Rich gold with bright highlight band and darker edges
        for y in range(y1, y2):
            vy = (y - y1) / max(1, height - 1)
            # Metallic highlight: bright band at ~30% from top
            highlight = 1.0 + 0.25 * max(0, 1.0 - abs(vy - 0.30) / 0.25)
            # Edge darkening
            edge = 1.0 - 0.2 * max(0, (vy - 0.8) / 0.2)
            edge *= 1.0 - 0.15 * max(0, (0.08 - vy) / 0.08)
            
            for x in range(x1, x2):
                vx = (x - x1) / max(1, width - 1)
                # Slight horizontal darkening at edges
                h_edge = 1.0 - 0.06 * (1.0 - 4 * (vx - 0.5) ** 2)
                
                r = min(255, int(210 * highlight * edge * h_edge))
                g = min(255, int(175 * highlight * edge * h_edge))
                b = min(255, int(55 * highlight * edge * h_edge * 0.85))
                pixels[x, y] = (r, g, b, 255)
    
    elif accent == "silver":
        import random
        random.seed(42)
        # Brushed steel with horizontal highlight
        brush_noise = [random.randint(-8, 8) for _ in range(height)]
        
        for y in range(y1, y2):
            yi = y - y1
            vy = yi / max(1, height - 1)
            # Metallic highlight band
            highlight = 1.0 + 0.20 * max(0, 1.0 - abs(vy - 0.35) / 0.30)
            # Edge darkening
            edge = 1.0 - 0.18 * max(0, (vy - 0.82) / 0.18)
            edge *= 1.0 - 0.12 * max(0, (0.06 - vy) / 0.06)
            # Brushed metal noise
            noise = brush_noise[yi % len(brush_noise)]
            
            for x in range(x1, x2):
                base = 175 + noise
                r = min(255, max(0, int(base * highlight * edge)))
                g = min(255, max(0, int((base + 3) * highlight * edge)))
                b = min(255, max(0, int((base + 8) * highlight * edge)))
                pixels[x, y] = (r, g, b, 255)
    
    elif accent == "bronze":
        # Warm copper/bronze with highlight
        for y in range(y1, y2):
            vy = (y - y1) / max(1, height - 1)
            highlight = 1.0 + 0.22 * max(0, 1.0 - abs(vy - 0.32) / 0.28)
            edge = 1.0 - 0.2 * max(0, (vy - 0.82) / 0.18)
            edge *= 1.0 - 0.12 * max(0, (0.06 - vy) / 0.06)
            
            for x in range(x1, x2):
                vx = (x - x1) / max(1, width - 1)
                h_edge = 1.0 - 0.05 * (1.0 - 4 * (vx - 0.5) ** 2)
                
                r = min(255, int(195 * highlight * edge * h_edge))
                g = min(255, int(140 * highlight * edge * h_edge))
                b = min(255, int(95 * highlight * edge * h_edge * 0.85))
                pixels[x, y] = (r, g, b, 255)
    
    elif accent == "white":
        # Clean white with very subtle edge shadow for depth
        for y in range(y1, y2):
            vy = (y - y1) / max(1, height - 1)
            # Very subtle depth
            shade = 1.0 - 0.06 * max(0, (vy - 0.85) / 0.15)
            shade *= 1.0 - 0.04 * max(0, (0.05 - vy) / 0.05)
            
            for x in range(x1, x2):
                v = min(255, int(248 * shade))
                pixels[x, y] = (v, v, v, 255)
    
    return img


def generate_qr_code(url, size=55):
    """Generate a QR code image for the given URL."""
    if not HAS_QR:
        return None
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                        box_size=3, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def get_font(size, bold=False):
    """Try to load a clean font, fall back to default."""
    if bold:
        candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFCompactText-Bold.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFCompactText-Regular.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for fp in candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_slab(card_image_path: str, grade: float, centering: float, corners: float,
                edges: float, surface: float, card_name: str = "Unknown Card",
                set_name: str = "", output_path: str = None) -> str:
    """
    Render a full UNDSR grading slab image matching the official mockup layout.
    Returns the path to the generated slab image.
    """
    tier_name, label_bg, text_color, accent = get_tier(grade)

    # ── Create base slab ──
    slab = Image.new("RGBA", (SLAB_WIDTH, SLAB_HEIGHT), (242, 242, 244, 255))
    draw = ImageDraw.Draw(slab)

    # Outer slab border
    draw.rounded_rectangle([2, 2, SLAB_WIDTH - 3, SLAB_HEIGHT - 3],
                           radius=CORNER_RADIUS, outline=(175, 175, 180, 255), width=3)
    draw.rounded_rectangle([8, 8, SLAB_WIDTH - 9, SLAB_HEIGHT - 9],
                           radius=CORNER_RADIUS - 4, outline=(200, 200, 205, 180), width=1)

    # ── Label background ──
    label_region = [12, 12, SLAB_WIDTH - 13, LABEL_HEIGHT]
    draw.rounded_rectangle(label_region, radius=CORNER_RADIUS - 6, fill=label_bg)

    # ── Fonts ──
    f_brand = get_font(38, bold=True)
    f_sub_brand = get_font(13)
    f_card = get_font(16, bold=True)
    f_set = get_font(16, bold=True)
    f_sg_label = get_font(13, bold=True)
    f_sg_value = get_font(13, bold=True)
    f_grade_big = get_font(68, bold=True)
    f_tier = get_font(16, bold=True)
    f_serial = get_font(11)

    # ── NOPAL CACTUS (large, left side, vertically centered) ──
    cactus_height = LABEL_HEIGHT - 30  # Fill most of the label height
    nopal = load_nopal_icon(cactus_height, color=text_color, label_bg=label_bg)
    
    cactus_x = 22
    if nopal:
        cactus_y = 12 + (LABEL_HEIGHT - 12 - nopal.height) // 2
        slab.paste(nopal, (cactus_x, cactus_y), nopal)
        draw = ImageDraw.Draw(slab)
        text_left = cactus_x + nopal.width + 10
    else:
        text_left = 30

    # ── UNDSR + THE UNDESIRABLES (next to cactus) ──
    brand_y = 20
    draw.text((text_left, brand_y), "UNDSR", fill=text_color, font=f_brand)
    draw.text((text_left, brand_y + 38), "THE UNDESIRABLES", fill=text_color, font=f_sub_brand)

    # ── Card name & set name (below UNDSR) ──
    info_y = brand_y + 56
    if set_name:
        draw.text((text_left, info_y), set_name.upper(), fill=text_color, font=f_set)
        info_y += 18
    draw.text((text_left, info_y), card_name.upper(), fill=text_color, font=f_card)

    # ── Sub-grades (2×2 grid at bottom of label) ──
    sg_y = LABEL_HEIGHT - 42
    sg_col1_lbl = text_left
    sg_col1_val = text_left + 90
    sg_col2_lbl = text_left + 130
    sg_col2_val = text_left + 220

    sub_grades = [
        ("CENTERING", centering, sg_col1_lbl, sg_col1_val, sg_y),
        ("CORNERS",   corners,   sg_col2_lbl, sg_col2_val, sg_y),
        ("EDGES",     edges,     sg_col1_lbl, sg_col1_val, sg_y + 18),
        ("SURFACE",   surface,   sg_col2_lbl, sg_col2_val, sg_y + 18),
    ]
    for label, val, lx, vx, sy in sub_grades:
        score_str = f"{val:.1f}" if val != int(val) else str(int(val))
        draw.text((lx, sy), label, fill=text_color, font=f_sg_label)
        draw.text((vx, sy), score_str, fill=text_color, font=f_sg_value)

    # ── BIG GRADE NUMBER (right side) ──
    grade_str = f"{grade:.1f}" if grade != int(grade) else str(int(grade))
    grade_bbox = draw.textbbox((0, 0), grade_str, font=f_grade_big)
    grade_w = grade_bbox[2] - grade_bbox[0]
    grade_x = SLAB_WIDTH - grade_w - 35
    grade_y = 16
    draw.text((grade_x, grade_y), grade_str, fill=text_color, font=f_grade_big)

    # Tier name centered under grade
    tier_bbox = draw.textbbox((0, 0), tier_name, font=f_tier)
    tier_w = tier_bbox[2] - tier_bbox[0]
    tier_x = grade_x + (grade_w - tier_w) // 2
    draw.text((tier_x, grade_y + 72), tier_name, fill=text_color, font=f_tier)

    # ── Apply metallic/holographic gradient ──
    slab = add_metallic_gradient(slab, label_region, accent)
    draw = ImageDraw.Draw(slab)

    # ── Card image ──
    try:
        card_img = Image.open(card_image_path).convert("RGBA")
        card_area_w = SLAB_WIDTH - (CARD_PADDING * 2) - 20
        card_area_h = CARD_AREA_BOTTOM - CARD_AREA_TOP - 30

        cw, ch = card_img.size
        ratio = min(card_area_w / cw, card_area_h / ch)
        new_w = int(cw * ratio)
        new_h = int(ch * ratio)
        card_img = card_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        card_x = (SLAB_WIDTH - new_w) // 2
        card_y = CARD_AREA_TOP + (card_area_h - new_h) // 2 + 10

        # Drop shadow
        shadow = Image.new("RGBA", (new_w + 10, new_h + 10), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [0, 0, new_w + 9, new_h + 9], radius=6, fill=(0, 0, 0, 45))
        slab.paste(shadow, (card_x - 3, card_y + 3), shadow)

        # Paste card
        slab.paste(card_img, (card_x, card_y), card_img)

        draw = ImageDraw.Draw(slab)
        draw.rounded_rectangle(
            [card_x - 1, card_y - 1, card_x + new_w + 1, card_y + new_h + 1],
            radius=4, outline=(150, 150, 155, 200), width=1)
    except Exception:
        draw.text((SLAB_WIDTH // 2 - 60, SLAB_HEIGHT // 2),
                  "CARD IMAGE", fill=(180, 180, 180), font=f_card)

    # ── Bottom bar: serial + QR ──
    serial = f"UNDSR-{uuid.uuid4().hex[:10].upper()}"
    bottom_y = SLAB_HEIGHT - 60

    draw.text((30, bottom_y + 8), serial, fill=(110, 110, 115), font=f_serial)

    site_text = "the-undesirables.com"
    site_bbox = draw.textbbox((0, 0), site_text, font=f_serial)
    site_w = site_bbox[2] - site_bbox[0]
    draw.text(((SLAB_WIDTH - site_w) // 2, bottom_y + 22), site_text,
              fill=(140, 140, 145), font=f_serial)

    qr_img = generate_qr_code(WEBSITE_URL, size=55)
    if qr_img:
        slab.paste(qr_img, (SLAB_WIDTH - 80, bottom_y - 2), qr_img)

    # ── Save ──
    if output_path is None:
        out_dir = Path.home() / "Desktop"
        safe_name = card_name.replace(" ", "_").replace("/", "-")[:30]
        output_path = str(out_dir / f"UNDSR_{grade_str}_{tier_name.replace(' ', '_')}_{safe_name}.png")

    slab.convert("RGB").save(output_path, "PNG", quality=95)
    return output_path


def render_slab_from_grade_result(card_image_path: str, grade_result: dict, output_path: str = None) -> str:
    """Convenience function: takes grade_tcg_card() output → slab image."""
    report = grade_result.get("report", grade_result)
    return render_slab(
        card_image_path=card_image_path,
        grade=float(report.get("overall_grade", 7)),
        centering=float(report.get("centering", {}).get("score", 7)),
        corners=float(report.get("corners", {}).get("score", 7)),
        edges=float(report.get("edges", {}).get("score", 7)),
        surface=float(report.get("surface", {}).get("score", 7)),
        card_name=report.get("card_identified", "Unknown Card"),
        output_path=output_path
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UNDSR Slab Renderer v3")
    parser.add_argument("card_image", help="Path to the card photo")
    parser.add_argument("--grade", type=float, required=True)
    parser.add_argument("--centering", type=float, required=True)
    parser.add_argument("--corners", type=float, required=True)
    parser.add_argument("--edges", type=float, required=True)
    parser.add_argument("--surface", type=float, required=True)
    parser.add_argument("--name", default="Unknown Card")
    parser.add_argument("--set", default="")
    parser.add_argument("--output", default=None)

    args = parser.parse_args()
    out = render_slab(
        card_image_path=args.card_image, grade=args.grade,
        centering=args.centering, corners=args.corners,
        edges=args.edges, surface=args.surface,
        card_name=args.name, set_name=args.set, output_path=args.output
    )
    print(f"✅ UNDSR Slab rendered: {out}")
