# Calculate pHashes

A Python script that computes a 64-bit DCT [perceptual hash](https://en.wikipedia.org/wiki/Perceptual_hashing) for every card printing image and writes the results back into `csvs/english/card-printing.csv` as the `Image Hash Full` and `Image Hash Art` columns. From there they flow into `phash_full` / `phash_art` in the JSON files and the SQL DB.

The point of these hashes is image recognition: given a photo of a card, an application can compute the same hash locally and look up the printing by finding the closest hash in the dataset. To make that work, an application has to reproduce the calculation *exactly* — the same crop, the same downsample, the same DCT. This document describes how.

Images are read from the [Download All Images](/helper-scripts/download-all-images/README.md) cache (`../download-all-images/images`) and downloaded on a cache miss.

## Running the Script with System Python

### Initial Setup

1. Ensure your system python is compatible with the python version listed in `pyproject.toml`.
2. Ensure all required packages are installed (`requests`, `Pillow`, `numpy`).

### Running the Script

1. Run `python main.py` to compute hashes for every printing that doesn't already have one.
2. Run with the flags below to narrow or force the work.

## Running the Script with Pyenv

### Initial Setup

1. Install [pyenv](https://github.com/pyenv/pyenv).
2. Run `pyenv install` to install the Python version.
3. Install [poetry](https://python-poetry.org/).
    * I recommend using `pyenv exec pip install poetry`.
4. Run `pyenv exec poetry install` to install packages.

### Running the Script

1. Run `pyenv exec poetry run python main.py`.
2. Or run `./helper-scripts/calculate-phashes.sh` from the repo root, which does the above for you.

### Flags

| Flag | Effect |
| --- | --- |
| `-s`, `--set-id <set-id>` | Only process printings from that set. Ex: `-s WTR` |
| `-l`, `--min-id <n>` | With `-s`, skip printings numbered below `n`. |
| `-m`, `--max-id <n>` | With `-s`, skip printings numbered above `n`. |
| `-f`, `--force` | Recalculate hashes that are already populated. |
| `--debug-crop <print-id>` | Write the `full` and `art-regular` crops for one printing to `debug-crops/` instead of hashing anything. Ex: `--debug-crop WTR001` |

The run is incremental — printings that already have a full hash are skipped unless `--force` is passed — and progress is flushed to the CSV every 200 rows and again on exit, so an interrupted run resumes cheaply.

Use `--debug-crop` whenever you touch the bounds below. It's the quickest way to confirm a rectangle actually lands on the artwork.

## How the hash is calculated

```
function phash(image, bbox):
    region = crop(image, bbox)
    gray   = area_average_downsample(region, 32, 32)  # 0.299R + 0.587G + 0.114B

    dct    = dct2(gray)                # 2D DCT-II
    block  = dct[0:8, 0:8]             # low-frequency corner
    coeffs = block minus the DC term   # 63 values

    median = median(coeffs)
    bits   = [0]                       # placeholder for the dropped DC term
    bits  += [1 if c > median else 0 for c in coeffs]

    return uint64(bits, msb_first)     # stored as a decimal string
```

Applied per printing, against the image rotated upright using the printing's `image_rotation_degrees`:

```
phash_full = phash(image, FULL_BBOX)

if not played_horizontally:
    phash_art = phash(image, REGULAR_ART_BBOX)
```

### Reproducing it exactly

Four details will silently produce different hashes if you get them wrong. Every step below is deliberately something any language can reproduce exactly, so don't reach for an imaging library's conveniences.

- **The downsample is an area average, not a resampling filter.** Each of the 32×32 output cells is the mean of the source pixels in its box, where the box edges are `floor(i * size / 32)` and `ceil((i + 1) * size / 32)`. Do **not** substitute `PIL.resize()` with `LANCZOS` or `BICUBIC` — those apply a sharpening kernel that shifts near-median DCT coefficients and flips hash bits.
- **The DCT is unnormalized DCT-II**, i.e. the plain matrix product `C · gray · Cᵀ` where `C[u][x] = cos((2x + 1) · u · π / 64)`. An orthonormal DCT (`scipy.fft.dct(..., norm='ortho')`) scales the `u = 0` row differently from the rest, which changes how the first row and column of the 8×8 block compare against the median.
- **The DC term is excluded from the median, but kept as a leading `0` bit.** Dropping it outright would leave a 63-bit value. The leading zero also means every hash is `< 2^63`, so it fits in a signed 64-bit integer.
- **Hashes are stored as decimal strings.** A 64-bit value exceeds `Number.MAX_SAFE_INTEGER`, so a JS consumer parsing the JSON as a number would silently lose the low bits — exactly the ones the comparison depends on. Parse into a `BigInt` or an explicit `uint64`.

## Cropping bounds

The two bounding boxes are expressed as `(x, y, width, height)` **fractions of the upright card image**, so they're independent of resolution:

| Box | `(x, y, w, h)` | Horizontal extent | Vertical extent |
| --- | --- | --- | --- |
| `FULL_BBOX` | `(0.00, 0.00, 1.00, 1.00)` | 0% → 100% | 0% → 100% |
| `REGULAR_ART_BBOX` | `(0.10, 0.16, 0.80, 0.42)` | 10% → 90% | 16% → 58% |

The full box is the entire card image, black border included. The art box is the rectangle that the artwork occupies on a standard (non-full-art) card face.

On the 450×628 gallery images this dataset hashes, the art box works out to the pixel rectangle `(45, 100) → (405, 364)`.

### What the bounds assume about your image

The fractions are only meaningful if your image is the card and nothing but the card. When hashing a photo in order to match against this dataset, you need to first:

1. **Detect the card and rectify it.** Warp the card's four corners to a rectangle so the result is the card's full bleed — corner to corner, *including* the black border, with no background padding and nothing cropped off the edges. The gallery images have an aspect ratio of ~0.716 (450×628), which is the physical 63mm × 88mm card, so a correctly rectified capture should land near that ratio.
2. **Rotate it upright**, so the name bar is at the top and the text box at the bottom. This script does that with `image_rotation_degrees`, which it applies as a *counter-clockwise* rotation.
3. **Then apply the fractions above** and hash.

Padding of even a few percent shifts every fraction, which moves the art box off the artwork and changes every bit of the full hash. This is the most common reason a locally-computed hash fails to match.

### Why the art box is fixed, even for full-art prints

The art box is *always* `REGULAR_ART_BBOX`, including for full-art (`FA`) printings whose artwork actually bleeds to the card edge.

This looks wrong but is deliberate. At scan time an application is looking at a photo and cannot know whether the card in frame is a full-art print — that's the thing it's trying to identify. So it crops every upright card with the same fixed rectangle. For the lookup to succeed, the stored hash has to be whatever that fixed crop produces, so full-art prints are hashed on the regular art rect too.

### Cards without an art hash

`phash_art` is skipped entirely for cards where `played_horizontally` is true — the card is landscape, so the art rectangle doesn't correspond to its artwork. Those printings still get a `phash_full`, computed on the upright-rotated image. `phash_full` itself is only absent when the printing has no `image_url`.

## Matching against the dataset

Compare two hashes by **Hamming distance**: parse both to 64-bit integers, XOR them, and count the set bits. Identical images give 0; the smaller the distance, the closer the match. Take the minimum across the dataset, and calibrate a rejection cutoff empirically against your own capture pipeline rather than assuming one.

**Neither hash uniquely identifies a printing.** A 64-bit hash of a 32×32 grayscale reduction simply cannot resolve small details, so:

- **`phash_art` identifies the artwork.** Every printing that reuses an art gets the same art hash — across sets, rarities and foilings. In the English dataset roughly 16k printings collapse to fewer than 5k distinct art hashes.
- **`phash_full` discriminates better but not perfectly**, since it also sees the border, set symbol and rarity. Roughly 16k printings collapse to about 6.4k distinct full hashes, and more than half of those values are shared by two or more printings — printings that differ only by a foiling stamp or a small set symbol hash identically.

So treat a match as narrowing the answer to a *candidate set* of printings, then disambiguate with whatever else you have: the set symbol, the collector number, or asking the user.
