# Fetch CardVault Spoilers
A Python script that pulls newly revealed cards for the sets currently being spoiled out of the CardVault API and appends them to the CSVs.

## What it writes
It appends to three CSVs:

* **card.csv**
* **card-printing.csv**
* **card-face-association.csv**

## What it doesn't fill in
These columns are deliberately left blank, because they're a reading of the card rather than something the API knows. Each run's report lists them as a reminder:

* card.csv — `Arcane`, `Card Keywords`, `Abilities and Effects`, `Ability and Effect Keywords`, `Granted Keywords`, `Removed Keywords`, `Interacts with Keywords`
* card-printing.csv — `Expansion Slot`, `TCGPlayer ID`, `Image Rotation Degrees`

Art variations need a second look, the report calls out every printing that got one. Extended art (`EA`) and full art (`FA`) come straight from the API, but alternate art (`AA`), alternate border (`AB`), alternate text (`AT`) and half size (`HS`) have no CardVault equivalent, so a printing needing one of those will arrive blank, `EA` or `FA`. Check against the [Collector's Centre](https://fabtcg.com/collectors-centre/).

Anything the API describes in a way the CSVs have no term for — an unrecognised rarity, foiling or art type — is reported rather than guessed at, and the printing is left for manual entry.

## Double-faced cards
There are two kinds, and the script tells them apart by whether the printing's two faces point at the same card:

* A **Marvel** puts the same card on both sides. Both faces share a core, so `Is DFC` is `No`.
* A **flip card** like Viserai has a different card per side. Each face has its own core, so `Is DFC` is `Yes`, and both cards get their own card.csv row.

Either way the printing gets two card-printing.csv rows — same set number, same foiling, different image — plus one card-face-association.csv row. That association references card printing Unique IDs, which don't exist until `generate-unique-ids` has run, so the fetch pass stashes it in `pending-face-associations-<slug>.json` and `--link` writes it out. Front and back are matched back up by image URL, which is exact rather than a guess at a naming convention.

## Running it on a schedule
`.github/workflows/fetch-cardvault-spoilers.yml` runs this hourly, one job per set group. Each group gets a `spoilers/<slug>` branch that the job continues if it already exists, so a season's worth of drops accumulate on one branch behind one pull request. The groups live in the workflow's `SPOILER_GROUPS`; a `workflow_dispatch` input runs a one-off group without editing it.

Per run the job fetches, mints the Unique IDs, links, regenerates the data set, commits `csvs` and `json` by name, and then either opens the pull request or merges the new checklist items into the one that's open. The run report goes to the job summary.

## Set groups and branches
A run takes a **group** of set codes, and one group is meant to become one branch:

```
python main.py --sets MPW AOL     # one branch
python main.py --sets IAR         # another
```

Group sets that share a release date. Mastery Pack Warrior and Armory Deck Olympia land together and share printings, so putting them in one group keeps a card that appears in both from landing on two branches at once. Sets on different release dates should be separate runs.

Set codes come from `--sets` (space or comma separated) or the `SPOILER_SETS` environment variable.

Each group gets its own files, named from a **slug** made of its sorted set codes, so groups never tread on each other:

| Group | Slug | Report | Pending associations |
| --- | --- | --- | --- |
| `--sets MPW AOL` | `aol-mpw` | `report-aol-mpw.md` | `pending-face-associations-aol-mpw.json` |
| `--sets IAR` | `iar` | `report-iar.md` | `pending-face-associations-iar.json` |

The slug is sorted, so `--sets MPW AOL` and `--sets AOL MPW` are the same group and won't produce two branches for the same work.

Under GitHub Actions the run appends `sets`, `slug`, `branch` (`spoilers/<slug>`), `report`, `cards`, `printings` and `changed` to `$GITHUB_OUTPUT`, so a workflow can branch and open a PR without re-deriving any of it. Outside Actions that's a no-op.

A set has to exist in set.csv and set-printing.csv before its cards can be added, since a new set needs a release date and product links this script has no business inventing. If it doesn't, the run reports that and skips the set.

## Running the Script with System Python
### Initial Setup
1. Ensure your system python is the same version as or compatible with the python version listed in `.python-version`. The script only uses the standard library, so there's nothing to install.

### Running the Script
Because `generate-unique-ids` is what mints Unique IDs, a full ingest is three steps:

1. Run `python main.py --sets MPW AOL` to append the new rows with blank Unique IDs.
2. Run `../generate-unique-ids.sh` to mint the Unique IDs.
3. Run `python main.py --link` to fill in `Card Unique ID` on the new printing rows and write out any pending face associations.

Then run `../pre-commit-scripts.sh` as usual to clean the CSVs, update legality, and regenerate the JSON.

## Running the Script with Pyenv
### Initial Setup
1. Install [pyenv](https://github.com/pyenv/pyenv).
2. Run `pyenv install` to install Python version.
3. Install [poetry](https://python-poetry.org/).
    * I recommend using `pyenv exec pip install poetry`.
4. Run `pyenv exec poetry install` to install packages.

### Running the Script
1. Run `pyenv exec poetry run python main.py --sets MPW AOL`, then the two steps above.

## Options
| Option | Explanation |
| --- | --- |
| `--sets` | The group of set codes this run covers, e.g. `--sets MPW AOL` or `--sets MPW,AOL`. Required unless `SPOILER_SETS` is set. |
| `--report-file` | Where to write the run report. Defaults to `report-<slug>.md`. |
| `--checklist-file` | Where to write the data entry items for `checklist.py`. Defaults to `checklist-<slug>.json`. |
| `--pending-file` | Where face associations wait between the fetch and `--link` passes. Defaults to `pending-face-associations-<slug>.json`; `--link` reads every stash in the folder unless this names one. |
| `--full` | Fetch details for every card in the set rather than only ones whose set number is absent from the CSVs. Slower, but picks up extra treatments (a rainbow foil, say) added to a card that's already been ingested. Worth running occasionally rather than every time. |
| `--link` | Fill in `Card Unique ID` on printing rows missing it, then exit. Run after `generate-unique-ids`. |
| `--dry-run` | Report only, write no CSVs. |

## The data entry checklist
A fetch writes two things about what it found: `report-<slug>.md`, a full account of the run, and `checklist-<slug>.json`, just the parts a person has to act on. `checklist.py` folds that second one into a pull request body:

```
python main.py --sets MPW AOL
gh pr view 123 --json body -q .body > body.md
python checklist.py --items checklist-aol-mpw.json --body body.md --output body.md
gh pr edit 123 --body-file body.md
```

Omit `--body` for a pull request that doesn't have one yet; omit `--output` to write to stdout. It reads and writes plain files rather than calling `gh` itself, so the workflow decides how the pull request is found.

A set arrives over weeks, so the checklist grows with the branch:

* New items are appended; items already in the body are left exactly as they are, ticked or not.
* Nothing is ever removed — a ticked box is a record of work done, and dropping it because a later run didn't mention that card would throw it away.
* Only the text between `<!-- cardvault-checklist:start -->` and `<!-- cardvault-checklist:end -->` is touched, so anything written above or below survives.
* Re-running over the same cards adds nothing.
* A pull request body can't exceed 65,536 characters. If the list would go over, the tail is dropped and the checklist says how many items didn't fit.

**Ticking a box doesn't gate anything.** It's shared scratch paper so the manual columns can be split up without two people doing the same card twice. Errors and the list of what was added stay in the report — the first are a property of the run rather than the data, and the second is already the diff.

## Row order
New rows are inserted in their sorted position rather than appended:

* **card.csv** by `Name`, with a card's pitches ascending beneath it
* **card-printing.csv** by `Card ID`, and within one set number the plain printing before its foils (`S`, `R`, `C`, `G`) and a double-faced printing's front before its back
* **card-face-association.csv** by `Front Card Printing`

Existing rows are never moved. Both files carry the odd row that doesn't follow the rule — Hyper Driver's pitches run 1, 2, 3, blank — and the order of printings sharing a set number is curated rather than derivable, so re-sorting the whole file would quietly rewrite all that and bury the run's real changes in the diff. Inserting keeps the diff purely additive.

## Notes
* Runs are idempotent — a second run over the same data adds nothing.
