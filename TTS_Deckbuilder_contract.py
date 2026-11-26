"""Generate Contracts cards, sheets, and TTS JSON from Google Sheets.
Run: python TTS_Deckbuilder_contracts.py
"""
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, unquote

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

SHEET_ID = "1pt8Rs9md5vhpLlYzadCavkDgH-GmtPQTXDnFh2VHu4g"
TAB_IDS = {"contracts": "1153292724"}
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output" / "contracts"
IMAGE_ASSETS_DIR = BASE_DIR / "ImageAssets"
CARD_WIDTH, CARD_HEIGHT = 750, 1050
CARDS_PER_ROW, MAX_ROWS = 5, 7
MAX_CARDS_PER_SHEET = CARDS_PER_ROW * MAX_ROWS
BLACK, WHITE, GRAY = (25, 25, 25), (255, 255, 255), (225, 225, 225)
TINT_STRENGTH = 0.83
COLOR_NAMES = {
    "parasite": (40, 128, 60), "overseer": (145, 7, 184),
    "disruption": (150, 30, 6), "economy": (95, 173, 5),
    "engineer": (196, 120, 6), "gambler": (204, 201, 33),
    "traveler": (21, 162, 194),
    "red": (190, 52, 44), "blue": (42, 118, 194),
    "green": (45, 147, 78), "yellow": (204, 201, 33),
    "purple": (145, 70, 180), "orange": (212, 132, 37),
    "gray": (110, 110, 110), "grey": (110, 110, 110),
    "black": (50, 50, 50), "white": (235, 235, 235),
}

def font(size, bold=False):
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
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
    draw.text(xy, str(text), font=f, fill=fill, anchor="mm", **kwargs)

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

def value(row, name, default=""):
    v = row.get(name, default)
    return default if pd.isna(v) else str(v).strip()

def number_value(row, name):
    v = value(row, name)
    if not v:
        return "-"
    try:
        n = float(v)
        return str(int(n)) if n.is_integer() else v
    except ValueError:
        return v

def parse_color(raw):
    """Use the hex value from the Contracts sheet for this card's color."""
    raw = str(raw).strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) == 6:
        try:
            return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    print(f"Warning: invalid hex Color {raw!r}; using neutral gray")
    return (100, 100, 100)

def tint(color):
    return tuple(round(c * (1 - TINT_STRENGTH) + 255 * TINT_STRENGTH) for c in color)

def valid_image(path):
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
    stem = Path(unquote(urlsplit(url).path)).stem or "artwork"
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:48]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{stem}_{digest}"

def resolve_artwork(source, cache_dir, base_dir, session):
    source = str(source).strip()
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
            if len(response.content) > 20 * 1024 * 1024:
                raise ValueError("Image exceeds 20 MB")
            with Image.open(BytesIO(response.content)) as image:
                image.load()
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("Image is not a PNG or JPEG")
                fmt = image.format
                dest = cache_dir / (prefix + (".png" if fmt == "PNG" else ".jpg"))
                image.save(dest, format=fmt)
            if not valid_image(dest):
                dest.unlink(missing_ok=True)
                raise ValueError("Downloaded image failed validation")
            print(f"Downloaded artwork: {dest.name}")
            return str(dest)
        except (requests.RequestException, OSError, ValueError) as exc:
            print(f"Warning: artwork unavailable: {source} ({exc})")
            return ""
    if parsed.scheme and not (len(parsed.scheme) == 1 and source[1:3] in (":\\", ":/")):
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
    cache_dir.mkdir(parents=True, exist_ok=True)
    cards = cards.copy()
    resolved = {}
    with requests.Session() as session:
        for raw in cards["Image"].fillna(""):
            source = str(raw).strip()
            if source and source not in resolved:
                resolved[source] = resolve_artwork(source, cache_dir, base_dir, session)
    cards["Image"] = [resolved.get(str(v).strip(), "") for v in cards["Image"].fillna("")]
    print(f"Artwork ready: {sum(bool(v) for v in cards['Image'])}/{len(cards)} contracts")
    return cards

def draw_art(img, image_value):
    if not image_value:
        return
    with Image.open(Path(image_value)) as source:
        source = ImageOps.exif_transpose(source).convert("RGBA")
        source.thumbnail((692, 405), Image.Resampling.LANCZOS)
        x = (CARD_WIDTH - source.width) // 2
        y = 120 + (405 - source.height) // 2
        img.paste(source, (x, y), source)

def draw_card(row):
    color = parse_color(value(row, "Color"))
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), tint(color))
    draw = ImageDraw.Draw(img)
    kind = value(row, "Type", "Contract") or "Contract"
    draw.rounded_rectangle((450, 30, 768, 105), radius=36, fill=color)
    centered(draw, (604, 67), kind.upper(), fit_font(draw, kind.upper(), 265, 36, True, stroke=3),
             fill=WHITE, stroke_width=3, stroke_fill=BLACK)
    draw_art(img, value(row, "Image"))
    draw = ImageDraw.Draw(img)
    title = value(row, "Contract Name")
    centered(draw, (375, 555), title, fit_font(draw, title, 665, 52, True))
    draw.line((40, 610, 710, 610), fill=(145, 145, 145), width=2)
    # Only display populated scoring levels. Single-level contracts get a
    # larger, centered badge; multi-level contracts share the available width.
    levels = [("Level 1", "Points Main"),
              ("Level 2", "Points Second"),
              ("Level 3", "Points Third")]
    active_levels = [(label, number_value(row, field))
                     for label, field in levels if value(row, field)]
    if not active_levels:
        print(f"Warning: no points provided for {title!r}")
    elif len(active_levels) == 1:
        label, points = active_levels[0]
        draw.rounded_rectangle((215, 626, 535, 738), radius=22,
                               fill=WHITE, outline=color, width=5)
        centered(draw, (375, 652), label, font(24, True))
        centered(draw, (375, 700), points,
                 fit_font(draw, points, 270, 60, True))
    else:
        count = len(active_levels)
        gap = 16
        available = 680
        badge_width = (available - gap * (count - 1)) // count
        left = (CARD_WIDTH - (badge_width * count + gap * (count - 1))) // 2
        for j, (label, points) in enumerate(active_levels):
            x0 = left + j * (badge_width + gap)
            x1 = x0 + badge_width
            draw.rounded_rectangle((x0, 631, x1, 725), radius=18,
                                   fill=WHITE, outline=color, width=4)
            centered(draw, ((x0 + x1) // 2, 655), label, font(19, True))
            centered(draw, ((x0 + x1) // 2, 694), points,
                     fit_font(draw, points, badge_width - 32, 39, True))
    body = value(row, "Requirements")
    f = font(27)
    lines = wrap(draw, body, f, 665)
    line_height = 36
    while len(lines) * line_height > 179 and f.size > 17:
        f = font(f.size - 2)
        line_height = f.size + 9
        lines = wrap(draw, body, f, 665)
    if len(lines) * line_height > 179:
        print(f"Warning: requirements too long for {title!r}; text may overlap footer")
    for i, line in enumerate(lines):
        draw.text((42, 750 + i * line_height), line, font=f, fill=BLACK)
    draw.rounded_rectangle((20, 938, 730, 1025), radius=20, fill=GRAY)
    centered(draw, (375, 981), "CONTRACT", font(34, True))
    draw.rounded_rectangle((4, 4, 746, 1046), radius=27, outline=BLACK, width=7)
    return img

def generate(cards, output):
    cards = cards.astype(object).fillna("").reset_index(drop=True)
    required = {"Contract Number", "Contract Name", "Points Main", "Points Second", "Points Third", "Requirements", "Type", "Color", "Image"}
    missing = required - set(cards.columns)
    if missing:
        raise ValueError(f"Missing Google Sheets columns: {', '.join(sorted(missing))}")
    output.mkdir(parents=True, exist_ok=True)
    generated = []
    for i, row in cards.iterrows():
        filename = output / f"card_{i:03}.png"
        print(f"Generating contract {i}: {value(row, 'Contract Name')}")
        img = draw_card(row)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        filename.write_bytes(buffer.getvalue())
        generated.append(filename)
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
    centered(draw, (375, 525), "CONTRACT", font(75, True), fill=(240, 240, 240))
    back.save(output / "back.png")
    custom_deck, deck_ids, contained = {}, [], []
    for i, row in cards.iterrows():
        deck_number = i // MAX_CARDS_PER_SHEET + 1
        card_id = deck_number * 100 + i % MAX_CARDS_PER_SHEET
        deck_ids.append(card_id)
        description = value(row, "Requirements")
        description += "\n" + " | ".join(f"{label}: {number_value(row, field)}" for label, field in
                                        [("Level 1", "Points Main"), ("Level 2", "Points Second"), ("Level 3", "Points Third")]
                                        if value(row, field))
        contained.append({"Name": "Card", "CardID": card_id,
                          "Nickname": value(row, "Contract Name"), "Description": description})
    for n, sheet_path in enumerate(sheets, 1):
        count = min(MAX_CARDS_PER_SHEET, len(cards) - (n - 1) * MAX_CARDS_PER_SHEET)
        custom_deck[str(n)] = {"FaceURL": sheet_path.name, "BackURL": "back.png",
                               "NumWidth": CARDS_PER_ROW, "NumHeight": math.ceil(count / CARDS_PER_ROW),
                               "BackIsHidden": True, "UniqueBack": False, "Type": 0}
    deck = {"ObjectStates": [{"Name": "DeckCustom", "Nickname": "Contracts Deck",
                              "DeckIDs": deck_ids, "CustomDeck": custom_deck,
                              "ContainedObjects": contained}]}
    (output / "deck.json").write_text(json.dumps(deck, indent=2), encoding="utf-8")
    print(f"Generated {len(generated)} contracts, {len(sheets)} cardsheets, and {output / 'deck.json'}")
    print("Note: TTS FaceURL/BackURL use local filenames; upload images to reachable URLs before importing into TTS.")

def load_google_sheet(card_type):
    gid = TAB_IDS[card_type]
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        cards = pd.read_csv(url, dtype={"Contract Number": str})
    except Exception as exc:
        raise RuntimeError("Could not load Contracts Google Sheet as CSV; check sharing permissions and tab ID") from exc
    print(f"Loaded {len(cards)} {card_type} cards from Google Sheets")
    return cards

def main():
    cards = load_google_sheet("contracts")
    required = {"Contract Number", "Contract Name", "Points Main", "Points Second", "Points Third", "Requirements", "Type", "Color", "Image"}
    missing = required - set(cards.columns)
    if missing:
        raise ValueError(f"Missing Google Sheets columns: {', '.join(sorted(missing))}")
    cards = prepare_artwork(cards, IMAGE_ASSETS_DIR, BASE_DIR)
    generate(cards, OUTPUT_DIR)

if __name__ == "__main__":
    main()
