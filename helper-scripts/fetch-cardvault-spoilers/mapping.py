"""
Translation between the CardVault API's vocabulary and the CSV columns in this repo.

Anything CardVault states outright (name, stats, text, rarity, foiling, artist, image) is
mapped here. Anything that is a human reading of the card - the keyword columns, arcane,
expansion slot, whether an art treatment is EA or FA or AA - is deliberately left blank and
reported instead, because a wrong value that looks confident is worse than an empty cell.
"""

import re

# csvs/english/rarity.csv
RARITIES = {
    "basic": "B",
    "common": "C",
    "rare": "R",
    "super-rare": "S",
    "majestic": "M",
    "legendary": "L",
    "fabled": "F",
    "promo-marvel": "V",
    "marvel": "V",
    "promo": "P",
    "token": "T",
}

# csvs/english/foiling.csv
FOILINGS = {
    "regular": "S",
    "rainbow-foil": "R",
    "cold-foil": "C",
    "gold-foil": "G",
}

# How a foiling is written in the readability-only descriptor columns of
# card-face-association.csv, e.g. the "CF Marvel" in "MPW004 - N (CF Marvel)".
FOILING_ABBREVIATIONS = {
    "R": "RF",
    "C": "CF",
    "G": "GF",
}

# csvs/english/art-variation.csv. CardVault reports extended art and full art directly, but
# has no way of saying alternate art, alternate border, alternate text or half size - see
# ART_VARIATION_CAVEAT.
ART_VARIATIONS = {
    "regular": "",
    "extended-art": "EA",
    "full-art": "FA",
    "alternate-art": "AA",
}

ART_VARIATION_CAVEAT = (
    "Extended art (EA) and full art (FA) come straight from the API. Alternate art (AA), "
    "alternate border (AB), alternate text (AT) and half size (HS) have no equivalent in "
    "CardVault, so a printing that needs one of those will arrive blank, EA or FA. Check "
    "against the card itself. A blank on a plain regular printing isn't flagged - there's "
    "nothing in the API to tell one apart from a regular printing that needs AA - "
    "so those are worth a look too when the set finishes spoiling."
)

# Columns this script never fills, because they're a judgement call about the card rather
# than a fact the API states. Listed in the report so they don't get silently forgotten.
UNFILLED_CARD_COLUMNS = [
    "Arcane",
    "Card Keywords",
    "Abilities and Effects",
    "Ability and Effect Keywords",
    "Granted Keywords",
    "Removed Keywords",
    "Interacts with Keywords",
]

UNFILLED_PRINTING_COLUMNS = [
    "Expansion Slot",
    "TCGPlayer ID",
    # Image Rotation Degrees describes how the image file needs turning, which isn't the same
    # thing as the card being played sideways. Of the 21 printings CardVault calls horizontal,
    # the CSVs say 0 ten times, nothing seven times and 270 twice - no rule to derive.
    "Image Rotation Degrees",
]


class UnmappedValue(Exception):
    """Raised when CardVault uses a value we have no CSV equivalent for."""

    def __init__(self, field, value):
        super().__init__(f"unmapped {field}: {value!r}")
        self.field = field
        self.value = value


def _first_face(print_data):
    faces = print_data.get("faces") or []
    return faces[0] if faces else {}


def card_name(core):
    return (core.get("name") or "").strip()


def card_pitch(core, face=None):
    return stat(core, face or {}, "pitch", "printed_pitch")


def card_key(core, face=None):
    """
    The (name, pitch) pair the CSVs use to identify a card independently of printing.

    Takes the face as well so the key matches the Pitch actually written to card.csv - they
    have to agree, or --link can't tie a printing back to its card.
    """

    return (card_name(core), card_pitch(core, face))


# Game icons CardVault writes one way in its raw text but renders as another. {g} has no
# icon of its own - CardVault's own renderer turns it into the life icon that {h} produces -
# and csvs/english/icon.csv only knows {h}. Checked against every card in the database that
# uses it; the renderer agreed every time.
ICON_ALIASES = {
    "{g}": "{h}",
}


def normalise_icons(text):
    for written, rendered in ICON_ALIASES.items():
        text = text.replace(written, rendered)
    return text


def normalise_dashes(text):
    """
    CardVault writes an em dash as "--"; the CSVs use a single hyphen.
    """

    return text.replace(" -- ", " - ")


# A bold run and whatever padding CardVault left inside it. The inner text can't contain a
# star, so the pair can only match the markers it opened with - a stray unclosed ** stays
# where it is rather than swallowing the paragraphs after it.
EMPHASIS = re.compile(r"\*\*(\s*)([^*]+?)(\s*)\*\*")


def normalise_emphasis(text):
    """
    Move any padding CardVault left inside a bold run outside of it.

    The markers are meant to wrap the words, but a fair few cards carry the space inside
    them - "**Blood Debt **", "**Instant **-- Discard a zombie" - which reads as a trailing
    space in the CSV and leaves the dash without the space in front of it that
    normalise_dashes is looking for. Both come out right once the padding is on the outside.
    """

    return EMPHASIS.sub(lambda match: f"{match[1]}**{match[2]}**{match[3]}", text)


def functional_text(core):
    """
    CardVault separates paragraphs with {br}; the CSVs use a blank line.

    Emphasis is normalised before the dashes, because a "**Instant **-- " only looks like
    the " -- " the CSVs write as " - " once its padding is back on the outside.
    """

    text = (core.get("textbox") or "").replace("{br}", "\n\n")
    text = normalise_icons(normalise_dashes(normalise_emphasis(text)))
    # Padding moved out of a bold run at the end of a paragraph is trailing whitespace now.
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def artists(face):
    """
    CardVault separates co-artists with " / "; the CSVs use ", ".
    """

    names = [name.strip() for name in (face.get("printed_artist") or "").split("/")]
    return ", ".join(name for name in names if name)


def flavor_text(face):
    """
    CardVault wraps flavor text in _underscores_ to italicise it, however the CSVs don't use any markup.
    Strip the underscores and any whitespace they leave
    """

    text = (face.get("printed_flavor_text") or "").strip()
    if len(text) > 1 and text.startswith("_") and text.endswith("_"):
        text = text[1:-1].strip()

    return normalise_dashes(text)


def types(core):
    """
    The Types column, ordered the way the type text reads.

    CardVault returns each group alphabetically rather than in printed order - Angry Bones
    comes back as classes ['Necromancer', 'Pirate'] against a typebox of "Pirate Necromancer
    Action - Attack" - so the typebox is what decides the order, with anything it doesn't
    mention falling back to talent, class, type, subtype.
    """

    names = []
    for group in ("core_talents", "core_classes", "core_types", "core_subtypes"):
        for entry in core.get(group) or []:
            name = (entry.get("name_en") or entry.get("name") or "").strip()
            name = name.strip("()").strip()
            if name and name not in names:
                names.append(name)

    typebox = core.get("typebox") or ""

    def position(item):
        index, name = item
        found = typebox.find(name)
        # Anything missing from the typebox keeps its group order, after the rest.
        return (found, index) if found >= 0 else (len(typebox) + index, index)

    ordered = [name for _, name in sorted(enumerate(names), key=position)]

    return ", ".join(ordered)


def stat(core, face, core_key, face_key):
    """
    A printed value, preferring the core but falling back to the face.

    Occasionally CardVault leaves stats off the core, so the face is worth
    checking before giving up and writing a blank.
    """

    value = str(core.get(core_key) or "").strip()
    if value:
        return value

    printed = face.get(face_key) if face else None
    return "" if printed is None else str(printed).strip()


def card_fields(core, face=None):
    """Build the card.csv columns this script is willing to fill."""

    face = face or {}
    orientation = (face.get("orientation") or "").strip()

    return {
        # Unique ID is left blank on purpose - generate-unique-ids fills it in.
        "Unique ID": "",
        "Name": card_name(core),
        "Color": (core.get("color") or "").strip().capitalize(),
        "Pitch": stat(core, face, "pitch", "printed_pitch"),
        "Cost": stat(core, face, "cost", "printed_cost"),
        "Power": stat(core, face, "power", "printed_power"),
        "Defense": stat(core, face, "defense", "printed_defense"),
        "Health": stat(core, face, "life", "printed_life"),
        "Intelligence": stat(core, face, "intellect", "printed_intellect"),
        "Types": types(core),
        "Traits": (core.get("traitbox") or "").strip(),
        "Functional Text": functional_text(core),
        "Type Text": (core.get("typebox") or "").strip(),
        "Card Played Horizontally": "Yes" if orientation == "horizontal" else "",
    }


def faces_in_order(print_data):
    """
    The printing's faces, front first.

    A single sided printing has one face. A double sided one has two, ordered by
    `layout_position` - 10 for the front, 20 for the back.
    """

    faces = print_data.get("faces") or []
    return sorted(faces, key=lambda face: face.get("layout_position") or 0)


def rarity_for(print_data):
    rarity = (print_data.get("rarity") or "").strip()
    if rarity not in RARITIES:
        raise UnmappedValue("rarity", rarity)
    return RARITIES[rarity]


def foiling_for(print_data):
    """
    The printing's foiling, which the CSVs record once per printing.

    Both faces of a double sided card share a finish, so the front face decides it.
    """

    finish = (_first_face(print_data).get("finish_type") or "").strip()
    if finish not in FOILINGS:
        raise UnmappedValue("finish_type", finish)
    return FOILINGS[finish]


def art_variation_for(face):
    art_type = (face.get("art_type") or "").strip()
    if art_type not in ART_VARIATIONS:
        raise UnmappedValue("art_type", art_type)
    return ART_VARIATIONS[art_type]


def art_variation_needs_checking(rarity, foiling, art_variation):
    """
    Whether a printing's Art Variations column is worth a person's eyes.

    It can be wrong in both directions, and only flagging one of them is what lets the other
    through - a blank reads as deliberate, so nobody goes looking.

    A value the script wrote can't be trusted, because the API only knows three of the
    variations the CSVs use - see ART_VARIATION_CAVEAT.

    A blank can't be trusted either, on a printing whose treatment usually carries a value.
    91% of the marvels already in the CSVs have one, and every marvel in DYN, MPW and SEA
    does, so a blank marvel is far likelier to be missing FA than to be right. Cold foils
    carry one about a quarter of the time, often enough to look. Rainbow foils (13%), gold
    foils (9%) and plain regular printings (3%) hardly ever do, and flagging those would
    bury the printings that need the attention.
    """

    if art_variation:
        return True

    return rarity == "V" or foiling == "C"


def is_same_card_both_sides(print_data):
    """
    Whether a two faced printing is one card printed twice.

    A Marvel is: both faces point at the same core. A flip card like Viserai, or a double
    sided token, has a core per face - the same piece of card, but two different cards on it.
    """

    faces = faces_in_order(print_data)
    return len(faces) == 2 and faces[0].get("core") == faces[1].get("core")


def is_double_faced_card(print_data):
    """
    Whether a two faced printing is two different cards rather than one card printed twice.

    A Marvel puts the same card on both sides, so both faces point at the same core and the
    Is DFC column reads No. A flip card like Viserai has a core per face, and reads Yes.
    """

    return len(faces_in_order(print_data)) == 2 and not is_same_card_both_sides(print_data)


def fill_blank_artists(fields_for_faces, print_data):
    """
    Give a face with no artist of its own the other face's.

    CardVault leaves printed_artist empty on the back of a marvel often enough to be worth
    handling - three of IAR's alone. Both sides are the same card there, so the front's
    artist is the back's by definition.

    A flip card or a double sided token is two different cards and those are drawn by
    different artists. Those are set as blank and get reported instead for manual review.
    """

    if not is_same_card_both_sides(print_data):
        return

    artist = next((fields["Artists"] for fields in fields_for_faces if fields["Artists"]), "")
    if not artist:
        return

    for fields in fields_for_faces:
        fields["Artists"] = fields["Artists"] or artist


def printing_descriptor(card_id, foiling, rarity):
    """
    The readability-only text in card-face-association.csv's printing columns.

    Matches what the recent sets use: "MPW004 - N (CF Marvel)", or just "DTD005 - N" when
    there's no treatment worth naming.
    """

    treatment = []
    if foiling in FOILING_ABBREVIATIONS:
        treatment.append(FOILING_ABBREVIATIONS[foiling])
    if rarity == "V":
        treatment.append("Marvel")

    descriptor = f"{card_id} - N"
    if treatment:
        descriptor += f" ({' '.join(treatment)})"

    return descriptor


def printing_fields(print_data, face, core, card_unique_id, set_printing_unique_id, card_id):
    """
    Build the card-printing.csv columns for one face of one printing.

    The CSVs carry a row per face, so a double sided printing produces two rows that differ
    by their image (and, on a flip card, by which card they're a printing of).

    Raises UnmappedValue if CardVault used a rarity, foiling or art type with no CSV
    equivalent, so that an unrecognised printing is reported rather than guessed at.
    """

    image = face.get("image") or {}

    return {
        # Unique ID is left blank on purpose - generate-unique-ids fills it in.
        "Unique ID": "",
        "Card Unique ID": card_unique_id,
        "Card Name": card_name(core),
        "Card Pitch": card_pitch(core, face),
        "Card ID": card_id,
        "Set Printing Unique ID": set_printing_unique_id,
        "Set ID": (print_data.get("print_set") or {}).get("set_code", ""),
        "Edition": "N",
        "Rarity": rarity_for(print_data),
        "Foiling": foiling_for(print_data),
        "Art Variations": art_variation_for(face),
        "Artists": artists(face),
        "Flavor Text": flavor_text(face),
        "Image URL": image.get("large") or image.get("normal") or "",
    }


# Some printings put the rarity letter after the set number - LGS007 comes back as LGS007-P
# and Welcome to Rathe's Alpha Alpha Rampage as WTR006-M. No Card ID in the CSVs carries one.
RARITY_SUFFIX = re.compile(r"-[A-Z]$")


def printed_code(print_data):
    """
    The set number as printed on the card, which is what the CSVs use for Card ID.

    CardVault's `print_id` carries a treatment suffix (MPW024-RF, IAR222-MV) and a language
    prefix (FR_, JA_); the face's `printed_code` drops both, but may add a rarity letter.

    Stripping that letter looks like it's only for legacy sets, and no set released since
    Part the Mistveil uses it - but it is load bearing. 104 printings across the promo sets
    the script can ingest (FAB, HER, LGS, KSU, TEA, RNR, BVO, IRA) still carry it, and every
    one of them is in the CSVs under the stripped code. Leaving the letter on would make all
    104 look like printings the CSVs don't have yet, and a --full sweep would append them a
    second time under a Card ID that doesn't exist.
    """

    return RARITY_SUFFIX.sub("", (_first_face(print_data).get("printed_code") or "").strip())

