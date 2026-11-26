"""Generate all technology card PNGs, sheets, and TTS JSON from Google Sheets.

Run: python TTS_Deckbuilder_tech.py
The Image column accepts HTTPS image URLs or local PNG/JPG paths.
Remote images are cached and validated in ImageAssets before rendering.
"""
import json
import hashlib
from io import BytesIO
from urllib.parse import urlsplit, unquote

import requests
import math
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont, ImageOps

SHEET_ID = "1pt8Rs9md5vhpLlYzadCavkDgH-GmtPQTXDnFh2VHu4g"
TAB_IDS = {"tech": "1171735710"}
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output/tech"
IMAGE_ASSETS_DIR = BASE_DIR / "ImageAssets"

CARD_WIDTH, CARD_HEIGHT = 750, 1050
CARDS_PER_ROW, MAX_ROWS = 5, 7
MAX_CARDS_PER_SHEET = CARDS_PER_ROW * MAX_ROWS
BLACK = (25, 25, 25)
WHITE = (255, 255, 255)
GRAY = (225, 225, 225)
ARCHETYPE_COLORS = {
    "Parasite": (40, 128, 60),
    "Overseer": (145, 7, 184),
    "Disruption": (150, 30, 6),
    "Economy": (95, 173, 5),
    "Engineer": (196, 120, 6),
    "Gambler": (204, 201, 33),
    "Traveler": (21, 162, 194),
}
DEFAULT_COLOR = (90, 90, 90)
# A pale tint of each archetype's original hue; Gambler is warm pastel yellow.
TINT_STRENGTH = 0.83


def font(size, bold=False):
    candidates = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
                  else ["arial.ttf", "DejaVuSans.ttf"])
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def fit_font(draw, text, width, start, bold=False, stroke=0):
    for size in range(start, 15, -2):
        f = font(size, bold)
        if draw.textbbox((0, 0), text, font=f, stroke_width=stroke)[2] <= width:
            return f
    return font(16, bold)


def centered(draw, xy, text, f, fill=BLACK, **kwargs):
    # anchor mm centers glyphs, including stroke, on the requested position.
    draw.text(xy, text, font=f, fill=fill, anchor="mm", **kwargs)


def wrap(draw, text, f, width):
    lines = []
    for paragraph in str(text).splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        line = ""
        for word in paragraph.split():
            test = (line + " " + word).strip()
            if line and draw.textlength(test, font=f) > width:
                lines.append(line)
                line = word
            else:
                line = test
        if line:
            lines.append(line)
    return lines


def tint(color):
    return tuple(round(c * (1 - TINT_STRENGTH) + 255 * TINT_STRENGTH) for c in color)


def value(row, name, default=""):
    v = row.get(name, default)
    return default if pd.isna(v) else str(v).strip()


def valid_image(path):
    """Return True only for a decodable PNG/JPEG file."""
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG"}:
                return False
            image.verify()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


def cached_filename(url):
    """Stable, collision-resistant filename based on the complete URL."""
    path = unquote(urlsplit(url).path)
    stem = Path(path).stem or "artwork"
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:48]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    # Extension comes from the actual downloaded image, not the URL.
    return f"{stem}_{digest}"


def resolve_artwork(image_value, cache_dir, base_dir, session):
    """Validate existing artwork; download remote artwork only if uncached."""
    source = str(image_value).strip()
    if not source:
        return ""
    parsed = urlsplit(source)
    if parsed.scheme.lower() in ("http", "https"):
        prefix = cached_filename(source)
        for ext in (".png", ".jpg"):
            candidate = cache_dir / (prefix + ext)
            if valid_image(candidate):
                return str(candidate)
            if candidate.exists():
                print(f"Invalid cached image, downloading again: {candidate.name}")
                candidate.unlink()
        try:
            response = session.get(source, timeout=20)
            response.raise_for_status()
            # Limit unexpectedly large downloads before image decoding.
            if len(response.content) > 20 * 1024 * 1024:
                raise ValueError("Image exceeds 20 MB")
            with Image.open(BytesIO(response.content)) as image:
                image.load()
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("Image is not a PNG or JPEG")
                ext = ".png" if image.format == "PNG" else ".jpg"
                dest = cache_dir / (prefix + ext)
                # Normalize and re-encode to ensure the cache contains image data.
                image.save(dest, format=image.format)
            if not valid_image(dest):
                dest.unlink(missing_ok=True)
                raise ValueError("Downloaded image did not validate")
            print(f"Downloaded artwork: {dest.name}")
            return str(dest)
        except (requests.RequestException, OSError, ValueError) as exc:
            print(f"Warning: artwork unavailable: {source} ({exc})")
            return ""
    if parsed.scheme:
        print(f"Warning: unsupported image source: {source}")
        return ""
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    if valid_image(path):
        return str(path)
    print(f"Warning: local image missing or invalid: {path}")
    return ""


def prepare_artwork(cards, cache_dir, base_dir):
    """Resolve all Image values before starting card rendering."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cards = cards.copy()
    if "Image" not in cards.columns:
        cards["Image"] = ""
    resolved = {}
    with requests.Session() as session:
        for raw in cards["Image"].fillna(""):
            source = str(raw).strip()
            if source and source not in resolved:
                resolved[source] = resolve_artwork(source, cache_dir, base_dir, session)
    cards["Image"] = [resolved.get(str(v).strip(), "") for v in cards["Image"].fillna("")]
    print(f"Artwork ready: {sum(bool(v) for v in cards['Image'])}/{len(cards)} cards")
    return cards


def draw_art(img, image_value, base_dir):
    if not image_value:
        return
    path = Path(image_value)
    with Image.open(path) as source:
        source = ImageOps.exif_transpose(source).convert("RGBA")
        source.thumbnail((692, 405), Image.Resampling.LANCZOS)
        x = (CARD_WIDTH - source.width) // 2
        y = 120 + (405 - source.height) // 2
        img.paste(source, (x, y), source)


def draw_card(row, base_dir):
    archetype = value(row, "Tech Archetype", "Unknown")
    color = ARCHETYPE_COLORS.get(archetype.title(), DEFAULT_COLOR)
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), tint(color))
    draw = ImageDraw.Draw(img)

    # Cost upper-left.
    draw.ellipse((24, 20, 122, 118), fill=(248, 248, 248), outline=BLACK, width=5)
    cost = value(row, "Cost")
    centered(draw, (73, 69), cost, fit_font(draw, cost, 78, 47, True))

    # Archetype upper-right. Retains the original archetype color.
    draw.rounded_rectangle((450, 30, 768, 105), radius=36, fill=color)
    label = archetype.upper()
    label_font = fit_font(draw, label, 265, 36, True, stroke=3)
    centered(draw, (604, 67), label, label_font, fill=WHITE,
             stroke_width=3, stroke_fill=BLACK)

    # Illustration is optional, and never recolored by the card background tint.
    draw_art(img, value(row, "Image"), base_dir)
    draw = ImageDraw.Draw(img)

    # Title and body deliberately below illustration area.
    title = value(row, "Tech Name")
    title_font = fit_font(draw, title, 665, 54, True)
    centered(draw, (375, 570), title, title_font)
    draw.line((40, 628, 710, 628), fill=(145, 145, 145), width=2)

    body = value(row, "Description")
    body_font = font(29)
    lines = wrap(draw, body, body_font, 665)
    line_height = 39
    available = 927 - 660
    while len(lines) * line_height > available and line_height > 22:
        size = max(17, body_font.size - 2)
        body_font = font(size)
        line_height = size + 9
        lines = wrap(draw, body, body_font, 665)
    if len(lines) * line_height > available:
        print(f"Warning: description too long for {title!r}; text may overlap footer")
    for i, line in enumerate(lines):
        draw.text((42, 660 + i * line_height), line, font=body_font, fill=BLACK)

    draw.rounded_rectangle((20, 938, 730, 1025), radius=20, fill=GRAY)
    kind = value(row, "Type")
    centered(draw, (375, 981), kind, fit_font(draw, kind, 650, 34, True))

    # Border last so artwork can never cover it.
    draw.rounded_rectangle((4, 4, 746, 1046), radius=27, outline=BLACK, width=7)
    return img


def generate(cards, output, image_dir):
    cards = cards.fillna("").reset_index(drop=True)
    required = {"Tech Name", "Description", "Tech Archetype", "Cost", "Type"}
    missing = required - set(cards.columns)
    if missing:
        raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
    output.mkdir(parents=True, exist_ok=True)
    generated = []
    for i, row in cards.iterrows():
        filename = output / f"card_{i:03}.png"

        try:
            print(f"Generating card {i}: {row['Tech Name']}")

            img = draw_card(row, image_dir)

            # Encode the PNG in memory first.
            from io import BytesIO

            buffer = BytesIO()
            img.save(buffer, format="PNG")

            # Write the encoded PNG to disk.
            filename.write_bytes(buffer.getvalue())

            generated.append(filename)

        except Exception as e:
            print(f"\nFAILED on card {i}")
            print(f"Card name: {row['Tech Name']}")
            print(f"Output path: {filename!r}")
            print(f"Image mode: {img.mode if 'img' in locals() else 'unknown'}")
            print(f"Error: {type(e).__name__}: {e}")
            raise

    sheets = []
    for sheet_index in range(math.ceil(len(generated) / MAX_CARDS_PER_SHEET)):
        group = generated[sheet_index * MAX_CARDS_PER_SHEET:(sheet_index + 1) * MAX_CARDS_PER_SHEET]
        rows = math.ceil(len(group) / CARDS_PER_ROW)
        sheet = Image.new("RGB", (CARD_WIDTH * CARDS_PER_ROW, CARD_HEIGHT * rows), WHITE)
        for j, path in enumerate(group):
            with Image.open(path) as card:
                sheet.paste(card, ((j % CARDS_PER_ROW) * CARD_WIDTH, (j // CARDS_PER_ROW) * CARD_HEIGHT))
        path = output / f"cardsheet_{sheet_index + 1}.png"
        sheet.save(path)
        sheets.append(path)

    back = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), (40, 40, 40))
    draw = ImageDraw.Draw(back)
    draw.rounded_rectangle((25, 25, 725, 1025), radius=25, outline=(220, 220, 220), width=6)
    centered(draw, (375, 525), "TECH", font(80, True), fill=(240, 240, 240))
    back.save(output / "back.png")

    custom_deck, deck_ids, contained = {}, [], []
    for i, row in cards.iterrows():
        deck_number = i // MAX_CARDS_PER_SHEET + 1
        card_id = deck_number * 100 + i % MAX_CARDS_PER_SHEET
        deck_ids.append(card_id)
        contained.append({"Name": "Card", "CardID": card_id,
                          "Nickname": value(row, "Tech Name"),
                          "Description": value(row, "Description")})
    for n, sheet_path in enumerate(sheets, 1):
        count = min(MAX_CARDS_PER_SHEET, len(cards) - (n - 1) * MAX_CARDS_PER_SHEET)
        custom_deck[str(n)] = {"FaceURL": sheet_path.name, "BackURL": "back.png",
                               "NumWidth": CARDS_PER_ROW,
                               "NumHeight": math.ceil(count / CARDS_PER_ROW),
                               "BackIsHidden": True, "UniqueBack": False, "Type": 0}
    deck = {"ObjectStates": [{"Name": "DeckCustom", "Nickname": "Technology Deck",
                              "DeckIDs": deck_ids, "CustomDeck": custom_deck,
                              "ContainedObjects": contained}]}
    (output / "deck.json").write_text(json.dumps(deck, indent=2), encoding="utf-8")
    print(f"Created {len(sheets)} cardsheets and {output / 'deck.json'}")
    print("Note: TTS FaceURL/BackURL values are local filenames; upload images to reachable URLs before importing into TTS.")


def load_google_sheet(card_type):
    if card_type not in TAB_IDS:
        raise ValueError(f"Unknown card type: {card_type}")
    gid = TAB_IDS[card_type]
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/export?format=csv&gid={gid}"
    )
    try:
        cards = pd.read_csv(url)
    except Exception as exc:
        raise RuntimeError(
            "Could not load Google Sheet as CSV. Check internet access, "
            "sharing permissions, and the sheet/tab IDs."
        ) from exc
    print(f"Loaded {len(cards)} {card_type} cards from Google Sheets")
    return cards


def main():
    cards = load_google_sheet("tech")
    cards = prepare_artwork(cards, IMAGE_ASSETS_DIR, BASE_DIR)
    generate(cards, OUTPUT_DIR, BASE_DIR)


if __name__ == "__main__":
    main()
