# Skill: Meme Machine — AI-Powered Content Creator

**Trigger:** "make me a meme", "create a meme", "marketing content", "content calendar", "brand voice", "meme machine"
**Context:** Helps the holder create viral marketing content for their business or personal brand
**Personality:** Student The Contrarian (The Contrarian)

## What This Skill Does

You are a creative marketing assistant. The holder wants you to help them create memes, social media content, and viral marketing material for their business. All tools are free.

## Capabilities

| Feature | How |
|---------|-----|
| **Template Memes** | PIL/Pillow — Drake, Expanding Brain, Surprised Pikachu, etc. |
| **AI Original Images** | generate_image tool or DALL-E 3 |
| **Brand Voice** | Define humor style so every meme sounds like your brand |
| **Caption Writer** | Generate 5+ caption variations per meme |
| **Content Calendar** | Pre-generate a week of content |
| **Video Memes** | Short clips with captions (PIL + FFmpeg) |

## Quick Start

```python
from PIL import Image, ImageDraw, ImageFont
import os

def create_meme(template_path, top_text, bottom_text, output_path):
    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    font_paths = [
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    ]
    font_size = int(h * 0.08)
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            font = ImageFont.truetype(fp, font_size)
            break
    if not font:
        font = ImageFont.load_default()
    def draw_outlined_text(draw, x, y, text, font, anchor="mm"):
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx or dy:
                    draw.text((x+dx, y+dy), text, font=font, fill="black", anchor=anchor)
        draw.text((x, y), text, font=font, fill="white", anchor=anchor)
    if top_text:
        draw_outlined_text(draw, w//2, int(h*0.08), top_text.upper(), font)
    if bottom_text:
        draw_outlined_text(draw, w//2, int(h*0.92), bottom_text.upper(), font)
    img.convert("RGB").save(output_path, quality=95)
```

## Industry Meme Packs

- **Barber/Salon**: "Just a trim" clients, fresh fade flexes, waiting room chaos
- **Restaurant**: Kitchen at 5PM vs 8PM, Yelp reviewers, "we close at 9" (enters at 8:58)
- **Trades**: "My buddy can do it cheaper" disasters, weekend emergency calls
- **Real Estate**: Listing photos vs reality, "cozy" = closet-sized
- **Fitness**: New Year gym vs February, "I'll start Monday"
- **Crypto**: Buy high sell low, "I'm in it for the tech"

## Export Sizes

| Platform | Size |
|----------|------|
| Instagram | 1080×1080 |
| X / Twitter | 1200×675 |
| TikTok / Reels | 1080×1920 |
| YouTube Thumbnail | 1280×720 |

> Full detailed instructions: https://github.com/sailorpepe/the-undesirables/blob/main/.agents/skills/meme-machine/SKILL.md
