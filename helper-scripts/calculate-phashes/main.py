import csv
import getopt
import sys
from os import makedirs
from os.path import exists
from pathlib import Path

import numpy as np
import requests
from PIL import Image

# --- Perceptual hash configuration ---

DCT_SIZE = 32
HASH_SIZE = 8

# Art-region crops as {x, y, w, h} ratios of the (upright) card image.
FULL_BBOX = (0.0, 0.0, 1.0, 1.0)
REGULAR_ART_BBOX = (0.10, 0.16, 0.80, 0.42)

# CSV columns we populate (two of the trailing empty columns in the header).
ART_COLUMN = "Image Hash Art"
FULL_COLUMN = "Image Hash Full"

# Where downloaded card images live. We share the cache with download-all-images.
PRIMARY_IMAGE_DIR = Path(__file__).parent / "../download-all-images/images"
SEARCH_IMAGE_DIRS = [PRIMARY_IMAGE_DIR, Path(__file__).parent / "images"]

CARD_CSV_PATH = Path(__file__).parent / "../../csvs/english/card.csv"
CARD_PRINTING_CSV_PATH = Path(__file__).parent / "../../csvs/english/card-printing.csv"

# The same CDN prefixes that download-all-images strips to derive a local path.
CDN_PREFIXES = [
    "https://storage.googleapis.com/fabmaster/media/images/",
    "https://storage.googleapis.com/fabmaster/cardfaces/",
    "https://dhhim4ltzu1pj.cloudfront.net/media/images/",
    "https://d2wlb52bya4y8z.cloudfront.net/media/cards/",
    "https://legendstory-production-s3-public.s3.amazonaws.com/media/cards/",
    "https://cdn.fabtcg.com/uploads/",
]

# DCT-II basis matrix matching: C[u, x] = cos((2x+1) * u * pi / (2N)).
_u = np.arange(DCT_SIZE).reshape(DCT_SIZE, 1)
_x = np.arange(DCT_SIZE).reshape(1, DCT_SIZE)
DCT_MATRIX = np.cos((2 * _x + 1) * _u * np.pi / (2 * DCT_SIZE))


def url_to_relative_path(image_url):
    rest = image_url
    for prefix in CDN_PREFIXES:
        rest = rest.replace(prefix, "")
    return rest


def find_local_image(image_url):
    rest = url_to_relative_path(image_url)
    for image_dir in SEARCH_IMAGE_DIRS:
        candidate = image_dir / rest
        if candidate.exists():
            return candidate
    return None


def download_image(image_url):
    rest = url_to_relative_path(image_url)
    target = PRIMARY_IMAGE_DIR / rest
    target_dir = target.parent
    if not exists(target_dir):
        makedirs(target_dir)
    print(f"Downloading {image_url}")
    response = requests.get(image_url)
    response.raise_for_status()
    with open(target, "wb") as handler:
        handler.write(response.content)
    return target


def load_upright_image(path, image_rotation_degrees):
    img = Image.open(path).convert("RGB")
    if image_rotation_degrees:
        # rotate() turns counter-clockwise; the field stores how far the stored
        # image must turn to read upright. Verify direction with --debug-crop.
        img = img.rotate(image_rotation_degrees, expand=True)
    return img


def _box_resize_gray(arr):
    """Area-average downsample an HxWx3 RGB array to DCT_SIZE x DCT_SIZE
    grayscale.
    """
    n = DCT_SIZE
    height, width = arr.shape[0], arr.shape[1]
    gray = np.empty((n, n), dtype=np.float64)
    for oy in range(n):
        y0 = max(0, int(np.floor(oy * height / n)))
        y1 = max(y0 + 1, min(height, int(np.ceil((oy + 1) * height / n))))
        for ox in range(n):
            x0 = max(0, int(np.floor(ox * width / n)))
            x1 = max(x0 + 1, min(width, int(np.ceil((ox + 1) * width / n))))
            cell = arr[y0:y1, x0:x1]
            r = cell[:, :, 0].mean()
            g = cell[:, :, 1].mean()
            b = cell[:, :, 2].mean()
            gray[oy, ox] = 0.299 * r + 0.587 * g + 0.114 * b
    return gray


def crop_resize_gray(img, bbox):
    width, height = img.size
    bx, by, bw, bh = bbox
    crop_w = max(round(width * bw), 1)
    crop_h = max(round(height * bh), 1)
    x = round(width * bx)
    y = round(height * by)
    region = img.crop((x, y, x + crop_w, y + crop_h))
    arr = np.asarray(region, dtype=np.float64)
    return _box_resize_gray(arr)


def phash_from_gray(gray):
    dct = DCT_MATRIX @ gray @ DCT_MATRIX.T
    block = dct[:HASH_SIZE, :HASH_SIZE]
    coeffs = [
        block[y, x]
        for y in range(HASH_SIZE)
        for x in range(HASH_SIZE)
        if not (x == 0 and y == 0)
    ]
    median = float(np.median(coeffs))
    value = 0
    # Leading 0 stands in for the excluded DC term, then 63 threshold bits, MSB first.
    for bit in [0] + [1 if c > median else 0 for c in coeffs]:
        value = value * 2 + bit
    return str(value)


def compute_hashes(image_url, image_rotation_degrees, art_variations, played_horizontally):
    path = find_local_image(image_url)
    if path is None:
        path = download_image(image_url)

    img = load_upright_image(path, image_rotation_degrees)

    phash_full = phash_from_gray(crop_resize_gray(img, FULL_BBOX))

    phash_art = ""
    if not played_horizontally:
        # Always the regular art rect — never FULL_BBOX for full-art ("FA")
        # prints. At scan time the app can't know a card's art type, so it
        # crops every upright card with this same fixed rect; the DB hash must
        # match that, so full-art prints are hashed on the regular rect too.
        phash_art = phash_from_gray(crop_resize_gray(img, REGULAR_ART_BBOX))

    return phash_art, phash_full


# --- CSV read/write helpers ---


def read_csv_rows(path):
    with path.open(newline="") as csvfile:
        return list(csv.reader(csvfile, delimiter="\t", quotechar='"'))


def write_csv_rows(rows):
    with CARD_PRINTING_CSV_PATH.open("w", newline="", encoding="utf8") as csvfile:
        writer = csv.writer(
            csvfile,
            delimiter="\t",
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerows(rows)


def ensure_hash_columns(header):
    if ART_COLUMN in header:
        idx_art = header.index(ART_COLUMN)
    else:
        idx_art = header.index("TCGPlayer ID") + 1
        header[idx_art] = ART_COLUMN

    if FULL_COLUMN in header:
        idx_full = header.index(FULL_COLUMN)
    else:
        idx_full = idx_art + 1
        header[idx_full] = FULL_COLUMN

    return idx_art, idx_full


# --- Printing selection from card-printing.csv ---


def load_played_horizontally():
    """Card Unique ID -> played horizontally, read from card.csv."""
    rows = read_csv_rows(CARD_CSV_PATH)
    header = rows[0]
    idx_unique_id = header.index("Unique ID")
    idx_horizontal = header.index("Card Played Horizontally")
    return {row[idx_unique_id]: row[idx_horizontal] == "Yes" for row in rows[1:]}


def iter_printings(rows, set_id_filter, min_id, max_id):
    header = rows[0]
    idx = {
        column: header.index(column)
        for column in (
            "Unique ID",
            "Card Unique ID",
            "Card ID",
            "Set ID",
            "Art Variations",
            "Image URL",
            "Image Rotation Degrees",
        )
    }
    played_horizontally_by_card = load_played_horizontally()

    for row in rows[1:]:
        image_url = row[idx["Image URL"]].strip()
        if image_url == "":
            continue

        card_id = row[idx["Card ID"]]
        if set_id_filter is not None:
            if row[idx["Set ID"]] != set_id_filter:
                continue
            card_id_number = int(card_id[3:])
            if min_id is not None and card_id_number < min_id:
                continue
            if max_id is not None and card_id_number > max_id:
                continue

        rotation = row[idx["Image Rotation Degrees"]].strip()
        art_variations = [
            variation
            for variation in row[idx["Art Variations"]].split(", ")
            if variation.strip() != ""
        ]

        yield {
            "unique_id": row[idx["Unique ID"]],
            "id": card_id,
            "image_url": image_url,
            "image_rotation_degrees": int(rotation) if rotation != "" else 0,
            "art_variations": art_variations,
            "played_horizontally": played_horizontally_by_card.get(
                row[idx["Card Unique ID"]], False
            ),
        }


def run(set_id_filter, min_id, max_id, force):
    rows = read_csv_rows(CARD_PRINTING_CSV_PATH)
    header = rows[0]
    idx_art, idx_full = ensure_hash_columns(header)

    row_by_unique_id = {row[0]: row for row in rows[1:]}

    printings = list(iter_printings(rows, set_id_filter, min_id, max_id))
    total = len(printings)
    print(f"Computing pHashes for {total} printings with images...")

    updated_since_save = 0

    def save():
        write_csv_rows(rows)

    try:
        for index, printing in enumerate(printings, start=1):
            row = row_by_unique_id.get(printing["unique_id"])
            if row is None:
                print(f"WARNING: {printing['id']} ({printing['unique_id']}) not found in CSV, skipping")
                continue

            already_full = row[idx_full].strip() != ""
            if already_full and not force:
                continue

            try:
                phash_art, phash_full = compute_hashes(
                    printing["image_url"],
                    printing["image_rotation_degrees"],
                    printing["art_variations"],
                    printing["played_horizontally"],
                )
            except Exception as error:
                print(f"ERROR computing {printing['id']} ({printing['unique_id']}): {error}")
                continue

            row[idx_art] = phash_art
            row[idx_full] = phash_full
            updated_since_save += 1
            print(f"[{index}/{total}] {printing['id']} full={phash_full} art={phash_art or '-'}")

            if updated_since_save >= 200:
                save()
                updated_since_save = 0
    finally:
        save()
        print("Saved card-printing.csv")


def debug_crop(print_id):
    out_dir = Path(__file__).parent / "debug-crops"
    if not exists(out_dir):
        makedirs(out_dir)

    rows = read_csv_rows(CARD_PRINTING_CSV_PATH)

    for printing in iter_printings(rows, None, None, None):
        if printing["id"] != print_id:
            continue

        img = load_upright_image(
            find_local_image(printing["image_url"]) or download_image(printing["image_url"]),
            printing["image_rotation_degrees"],
        )

        for label, bbox in (("full", FULL_BBOX), ("art-regular", REGULAR_ART_BBOX)):
            width, height = img.size
            bx, by, bw, bh = bbox
            crop_w = max(round(width * bw), 1)
            crop_h = max(round(height * bh), 1)
            x = round(width * bx)
            y = round(height * by)
            region = img.crop((x, y, x + crop_w, y + crop_h))
            out_path = out_dir / f"{print_id}-{label}.png"
            region.save(out_path)
            print(f"Saved {out_path}")
        return

    print(f"Could not find a printing with id {print_id} (and an image) in card-printing.csv")


HELP_STRING = (
    "main.py [-s <set-id>] [-l <min-id>] [-m <max-id>] [-f|--force] "
    "[--debug-crop <print-id>]"
)


def parse_args(argv):
    set_id_filter = None
    min_id = None
    max_id = None
    force = False
    debug_crop_id = None

    try:
        opts, _ = getopt.getopt(
            argv,
            "hs:l:m:f",
            ["help", "set-id=", "min-id=", "max-id=", "force", "debug-crop="],
        )
    except getopt.GetoptError:
        print("ERROR: ", HELP_STRING)
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print(HELP_STRING)
            sys.exit()
        elif opt in ("-s", "--set-id"):
            set_id_filter = arg
        elif opt in ("-l", "--min-id"):
            min_id = int(arg)
        elif opt in ("-m", "--max-id"):
            max_id = int(arg)
        elif opt in ("-f", "--force"):
            force = True
        elif opt == "--debug-crop":
            debug_crop_id = arg

    return set_id_filter, min_id, max_id, force, debug_crop_id


if __name__ == "__main__":
    set_id_filter, min_id, max_id, force, debug_crop_id = parse_args(sys.argv[1:])

    if debug_crop_id is not None:
        debug_crop(debug_crop_id)
        sys.exit()

    if set_id_filter is not None:
        message = f"Calculating pHashes only for {set_id_filter}"
        if min_id is not None:
            message += f" Min: {min_id}"
        if max_id is not None:
            message += f" Max: {max_id}"
        print(message)

    run(set_id_filter, min_id, max_id, force)
