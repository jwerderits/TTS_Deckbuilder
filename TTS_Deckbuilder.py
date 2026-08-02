
import os
import math
import json
import textwrap

import pandas as pd

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont


# --------------------------------------------
# SETTINGS
# --------------------------------------------

CARD_WIDTH = 750
CARD_HEIGHT = 1050

MARGIN = 40

CARDS_PER_ROW = 5

OUTPUT = "output"

FONT_FILE = "arial.ttf"      # change if needed
FONT_BOLD = "arialbd.ttf"

BACKGROUND = (245,244,236)
BLACK = (30,30,30)
WHITE = (255,255,255)

ARCHETYPE_COLORS = {
    "Parasite": (40, 128, 60),
    "Overseer": (145, 7, 184),
    "Disruption": (150, 30, 6),
    "Economy": (95, 173, 5),
    "Engineer": (196, 120, 6),
    "Gambler": (204, 201, 33),
    "Traveler": (21, 162, 194)
}

DEFAULT_COLOR = (90,90,90)


# --------------------------------------------
# FONT HELPERS
# --------------------------------------------

def font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_FILE, size)
    except:
        return ImageFont.load_default()


# --------------------------------------------
# AUTO FIT TEXT
# --------------------------------------------

def fit_text(draw, text, max_width, start_size, bold=False):

    size = start_size

    while size > 16:

        f = font(size, bold)

        if draw.textlength(text, font=f) <= max_width:
            return f

        size -= 2

    return font(16, bold)


# --------------------------------------------
# WRAP PARAGRAPH
# --------------------------------------------

def wrap(draw, text, font_obj, width):

    words = text.split()

    lines = []
    current = ""

    for word in words:

        test = word if current == "" else current + " " + word

        if draw.textlength(test, font=font_obj) <= width:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


# --------------------------------------------
# LOAD DATA
# --------------------------------------------

cards = pd.read_csv("cards.csv")

os.makedirs(OUTPUT, exist_ok=True)

generated = []


# --------------------------------------------
# DRAW EACH CARD
# --------------------------------------------

for i, card in cards.iterrows():

    img = Image.new(
        "RGB",
        (CARD_WIDTH, CARD_HEIGHT),
        BACKGROUND
    )

    draw = ImageDraw.Draw(img)

    color = ARCHETYPE_COLORS.get(
        str(card["Tech Archetype"]),
        DEFAULT_COLOR
    )

    # border

    draw.rounded_rectangle(
        (4,4,CARD_WIDTH-4,CARD_HEIGHT-4),
        radius=25,
        outline=(50,50,50),
        width=6
    )

    # banner

    draw.rounded_rectangle(
        (0,0,CARD_WIDTH,100),
        radius=20,
        fill=color
    )

    archetype_font = fit_text(
        draw,
        str(card["Tech Archetype"]),
        CARD_WIDTH-120,
        36,
        True
    )

    draw.text(
        (30,25),
        str(card["Tech Archetype"]).upper(),
        fill=WHITE,
        font=archetype_font
    )

    # COST CIRCLE

    cx = CARD_WIDTH-80
    cy = 50

    draw.ellipse(
        (cx-40,cy-40,cx+40,cy+40),
        fill=(240,240,240),
        outline=(40,40,40),
        width=3
    )

    cost_font = fit_text(
        draw,
        str(card["Cost"]),
        60,
        36,
        True
    )

    bbox = draw.textbbox((0,0),str(card["Cost"]),font=cost_font)

    tw = bbox[2]-bbox[0]
    th = bbox[3]-bbox[1]

    draw.text(
        (cx-tw/2,cy-th/2-2),
        str(card["Cost"]),
        fill=BLACK,
        font=cost_font
    )

    # TITLE

    title_font = fit_text(
        draw,
        str(card["Tech Name"]),
        CARD_WIDTH-80,
        52,
        True
    )

    y = 145

    bbox = draw.textbbox((0,0),str(card["Tech Name"]),font=title_font)

    tw = bbox[2]-bbox[0]

    draw.text(
        ((CARD_WIDTH-tw)/2,y),
        str(card["Tech Name"]),
        fill=BLACK,
        font=title_font
    )

    y += 80

    draw.line(
        (40,y,CARD_WIDTH-40,y),
        fill=(150,150,150),
        width=2
    )

    y += 35

    body_font = font(30)

    lines = wrap(
        draw,
        str(card["Description"]),
        body_font,
        CARD_WIDTH-80
    )

    for line in lines:

        draw.text(
            (40,y),
            line,
            fill=BLACK,
            font=body_font
        )

        y += 38

    # bottom ribbon

    ribbon_h = 90

    draw.rounded_rectangle(
        (
            20,
            CARD_HEIGHT-ribbon_h-20,
            CARD_WIDTH-20,
            CARD_HEIGHT-20
        ),
        radius=15,
        fill=(225,225,225)
    )

    type_font = fit_text(
        draw,
        str(card["Type"]),
        CARD_WIDTH-100,
        34,
        True
    )

    bbox = draw.textbbox((0,0),str(card["Type"]),font=type_font)

    tw = bbox[2]-bbox[0]
    th = bbox[3]-bbox[1]

    draw.text(
        (
            (CARD_WIDTH-tw)/2,
            CARD_HEIGHT-20-ribbon_h/2-th/2
        ),
        str(card["Type"]),
        fill=BLACK,
        font=type_font
    )

    filename = os.path.join(
        OUTPUT,
        f"card_{i:03}.png"
    )

    img.save(filename)

    generated.append(filename)


print("Generated", len(generated), "cards.")


# --------------------------------------------
# CARD SHEET
# --------------------------------------------
# --------------------------------------------
# CARD SHEETS (supports any number of cards)
# --------------------------------------------

MAX_ROWS = 7
MAX_CARDS_PER_SHEET = CARDS_PER_ROW * MAX_ROWS

sheet_count = math.ceil(len(generated) / MAX_CARDS_PER_SHEET)

cardsheets = []

for sheet_index in range(sheet_count):

    start = sheet_index * MAX_CARDS_PER_SHEET
    end = min(start + MAX_CARDS_PER_SHEET, len(generated))

    sheet_cards = generated[start:end]

    rows = math.ceil(len(sheet_cards) / CARDS_PER_ROW)

    sheet = Image.new(
        "RGB",
        (
            CARD_WIDTH * CARDS_PER_ROW,
            CARD_HEIGHT * rows
        ),
        (255,255,255)
    )

    for i, filename in enumerate(sheet_cards):

        img = Image.open(filename)

        x = (i % CARDS_PER_ROW) * CARD_WIDTH
        y = (i // CARDS_PER_ROW) * CARD_HEIGHT

        sheet.paste(img, (x,y))

    outfile = os.path.join(
        OUTPUT,
        f"cardsheet_{sheet_index+1}.png"
    )

    sheet.save(outfile)

    cardsheets.append(outfile)

print(f"Created {len(cardsheets)} cardsheets.")


# --------------------------------------------
# BACK IMAGE
# --------------------------------------------

back = Image.new(
    "RGB",
    (CARD_WIDTH,CARD_HEIGHT),
    (40,40,40)
)

draw = ImageDraw.Draw(back)

draw.rounded_rectangle(
    (25,25,CARD_WIDTH-25,CARD_HEIGHT-25),
    radius=25,
    outline=(220,220,220),
    width=6
)

title = "TECH"

f = font(80,True)

bbox = draw.textbbox((0,0),title,font=f)

tw = bbox[2]-bbox[0]
th = bbox[3]-bbox[1]

draw.text(
    (
        (CARD_WIDTH-tw)/2,
        (CARD_HEIGHT-th)/2
    ),
    title,
    fill=(240,240,240),
    font=f
)

back.save(
    os.path.join(OUTPUT,"back.png")
)


# --------------------------------------------
# DECK JSON
# --------------------------------------------

custom_deck = {}
deck_ids = []
contained = []

for i, row in cards.iterrows():

    deck_number = (i // MAX_CARDS_PER_SHEET) + 1
    local_index = i % MAX_CARDS_PER_SHEET

    card_id = deck_number * 100 + local_index

    deck_ids.append(card_id)

    contained.append({
        "Name": "Card",
        "CardID": card_id,
        "Nickname": row["Tech Name"],
        "Description": row["Description"]
    })

for deck_number, sheet in enumerate(cardsheets, start=1):

    cards_in_sheet = min(
        MAX_CARDS_PER_SHEET,
        len(cards) - (deck_number-1)*MAX_CARDS_PER_SHEET
    )

    rows = math.ceil(cards_in_sheet / CARDS_PER_ROW)

    custom_deck[str(deck_number)] = {
        "FaceURL": f"cardsheet_{deck_number}.png",
        "BackURL": "back.png",
        "NumWidth": CARDS_PER_ROW,
        "NumHeight": rows,
        "BackIsHidden": True,
        "UniqueBack": False,
        "Type": 0
    }

deck = {
    "ObjectStates": [{
        "Name": "DeckCustom",
        "Nickname": "Technology Deck",
        "DeckIDs": deck_ids,
        "CustomDeck": custom_deck,
        "ContainedObjects": contained
    }]
}