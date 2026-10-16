# Edit Card
An interactive Python script that looks a card up by name or print code and lets you edit its `card.csv` row, its `card-printing.csv` rows and the cards it references in `card-reference.csv`, without opening any of them.

```
python main.py                        # asks for a card name or print code
python main.py command and conquer    # opens the card straight away
python main.py IAR056                 # so does a print code
python main.py + Lunging Strike       # adds a new card
```

## Finding a card
* **By name** - the whole name or part of it. Case and punctuation are ignored, so `argh smash` finds `Argh... Smash!`.
* **By print code** - a `Card ID` such as `IAR056`. Longer codes with one inside them work too, so you can paste `IAR056-RF` or `U-ARC159` as CardVault writes them.

If more than one card matches - a card in three pitches, or the two sides of a double faced printing - it lists them and asks which. Closing a card brings that list back, on the card you just closed, so you can work through the matches one after another. `q` (or Enter with `--plain`) leaves the list for a new search.

At the search prompt `↑` and `↓` go back through what you've searched for since starting the script, most recent first. They're forgotten when it ends.

## Editing
The card opens as a list of its `card.csv` fields, then the cards it references, then its printings. Move through it with the arrow keys.

| Key | What it does |
| --- | --- |
| `↑` `↓` | Move the highlight. `Page Up`, `Page Down`, `Home` and `End` move further, and `j` / `k` work too. |
| `Enter` | On a field, edit it: pick from a list where the field has one (see below), otherwise change the value on a line. On a printing, open it. On **Add reference…** or a reference, open the list of cards to reference. On **Add printing…**, add a printing. |
| `t` | Type the highlighted field's value on a line, even if it has a list. The current value is there ready to change; clear it to blank the field. |
| `e` | Edit the highlighted field in `$EDITOR` instead, which is easier for long functional text. |
| `a` | Add a printing, asking for its fields one after another (see below) - the same as **Add printing…**, the last row under the printings. |
| `c` | Add a printing as a copy of the highlighted one, going through its fields to change what differs. |
| `d` | On a printing, mark it for deletion - `d` again keeps it. On a reference, remove it. |
| `s` | Save. |
| `q` or `Esc` | Close the card. If there are unsaved changes it lists them: `Enter` saves, `n` discards, `c` keeps editing. In a printing, go back to the card. |

Changed fields are marked `*`, new printings `+` and deleted ones `-`. Ctrl-C backs out of a field without changing it.

Line breaks in `Functional Text` and `Flavor Text` are shown and typed as `\n`.

`e` needs `$EDITOR` (or `$VISUAL`) to be a command that waits for the file to be closed, e.g. `EDITOR=nano` or `EDITOR="code --wait"`.

### Fields with a list behind them
Fields whose values are defined in another CSV open as a list. Type to narrow it, `↑` `↓` to move, `Enter` to choose and `Esc` to go back.

| Field | List |
| --- | --- |
| `Color` | Red, Yellow, Blue, Purple or blank |
| `Types` | `type.csv` |
| `Card Keywords`, `Ability and Effect Keywords`, `Granted Keywords`, `Removed Keywords`, `Interacts with Keywords` | `keyword.csv` |
| `Abilities and Effects` | `ability.csv` |
| `Artists` | `artist.csv` |
| `Edition`, `Rarity`, `Foiling`, `Art Variations` | their own CSVs |
| `Set ID`, `Set Printing Unique ID` | `set.csv`, `set-printing.csv` |
| The legality columns, `Card Played Horizontally`, `Expansion Slot` | Yes / No |

Fields that hold several values (keywords, types, artists, art variations) stay open as you add and remove: `Enter` ticks or unticks the highlighted value and `Esc` finishes. New values go on the end, so use `t` if the order needs changing.

The short lists - edition, rarity, foiling, art variation, set - are complete, so nothing else is accepted. The rest are a starting point rather than the whole story:

* Each value shows how many cards or printings use it. Values that are in use but missing from the CSV are listed too, marked as such, so `Ice Fusion` or a type that hasn't been added to `type.csv` yet can still be picked.
* Picking a keyword written with an X, like `Ward X`, asks for its number on the line under the list: type `3` and it adds `Ward 3`. Anything but a number (or X) is refused, and `Esc` goes back to the list. Typing `ward 3` into the list does the same in one go.
* Typing something the list doesn't have offers to add it, last in the list. A value that isn't in the CSV or on any other row gets a note when it's added, since a typo looks just like a new keyword.

### References
**Add reference…**, at the end of the References section, opens a list of every card to tick the ones this card references - Become the Shadow Lord references Runechant and Gate to i'Arathael. Type a name or print code to narrow it, `Enter` ticks or unticks, `Esc` finishes. `Ctrl-C` leaves without changing anything.

A card refers to another by name, so a reference covers every pitch of it: ticking Surging Strike adds a row for the red, yellow and blue. Cards that share a name but not a type line stay separate, so the Hyper Driver token and the Hyper Driver attacks are picked on their own.

If the card you're editing comes in more than one pitch, you're asked whether to make the same change to the others, since a card's pitches nearly always reference the same things. `Enter` does, `n` changes just this one.

New rows go where the file would have them: in card name order, then by the name referenced and the pitches.

### Adding a card or printing
Type `+` at the search prompt to add a card - `+ Lunging Strike` starts it with that name. The fields are then asked for one after another, as a form, with the field being asked highlighted on the card: a list to pick from where the field has one, a line to type on otherwise. `Enter` keeps what a field holds and moves on, so a field that should stay blank is just `Enter`. Fields are asked for in the order they're listed on the card - the same order as the CSV, and as every other view in the script - and the pitch is filled in from the colour, ready to keep.

Once the card's fields are done it offers to add its first printing. **Add printing…** under a card's printings, `a`, and `c` on a printing go through the same form for a printing. The card ID fills in the set, and for a set that's only been printed once - every set but the first few - the set printing and edition as well; fields filled in like that are passed over. For a set with more than one edition (WTR, ARC, CRU, MON, ELE) the set printing is asked next, and choosing it fills in the edition. Afterwards the printing is shown, to look over before going back to the card.

Made a mistake a few fields back? Go back to it - the form moves both ways, and what you'd typed is kept:

| Key | In a field that's typed | In a field with a list |
| --- | --- | --- |
| `Enter` | Keep it and move on | Choose (or tick) the highlighted value |
| `↑` `↓` | Previous / next field | Move through the list - off its top or bottom changes field |
| `←` `→` | Move along the line | Previous / next field |
| `Shift-Tab` `Tab` | Previous / next field | Previous / next field |
| `Esc` | Move on, leaving it as it was | Move on |

While typing, `Home` / `End` (or `Ctrl-A` / `Ctrl-E`), `Delete`, `Ctrl-U`, `Ctrl-K` and `Ctrl-W` edit the line. Whatever a field filled in along the way - the set from a card ID, say - is shown under the next one.

`Ctrl-C` stops a form at any point, keeping what's been filled in so far to carry on with field by field. Nothing is written until you save: a new card goes into `card.csv` in name order. With `--plain` the form goes one way, a field after another.

### A card's other pitches
A card's pitches nearly always share their `Traits`, keyword and ability columns, so after changing one of those on a card that comes in other pitches, you're asked whether to make the same change to them. `Enter` does, `n` keeps it to this one.

It's the change that's copied, not the value: whatever you added is added to the others and whatever you removed is removed. A keyword with a number is the exception - a pitch that already has its own `Ward` or `Opt` keeps its number, and one that's copied over gets a note to check it, since the number often goes down with the pitch.

The other pitches' changes are listed and saved along with the card's own.

### Typing commands instead
`python main.py --plain` numbers the fields and takes typed commands rather than arrow keys. The script also works this way on its own when it isn't attached to a terminal, and on Windows.

| Command | What it does |
| --- | --- |
| `<n>` | Edit field `n`. |
| `e<n>` | Edit field `n` in `$EDITOR`. |
| `p<n>` | Open printing `n`, where `<n>` and `e<n>` edit its fields. `b` goes back. |
| `r` | Add a reference: type the name or print code of the card it references. |
| `dr<n>` | Remove reference `n`. |
| `a` | Add a printing, blank or as a copy of another. |
| `d<n>` | Mark printing `n` for deletion. `d<n>` again keeps it. |
| `s` | Save. |
| `q` | Close the card. If there are unsaved changes it lists them: Enter saves, `n` discards, `c` keeps editing. |
| Enter | Show the card again. |

## What it fills in for you
* `Edition`, `Rarity`, `Foiling`, `Art Variations` and `Set ID` are checked against their CSVs, and Yes/No columns only take `Yes`, `No` or blank. Lower case is tidied up.
* Typed keywords, types, abilities and artists are respelled the way they're already known - `go again` becomes `Go again` - and comma spacing is tidied.
* Changing a printing's `Card ID` sets its `Set ID` to match, and changing `Card ID`, `Set ID` or `Edition` looks up the `Set Printing Unique ID` from `set-printing.csv`.
* Renaming a card, or changing its pitch, carries into the `Card Name` and `Card Pitch` of its printings. Other CSVs that write the name out (the legality CSVs, `card-reference.csv`) are listed when you save, but not changed.
* Changing a printing's `Image URL` clears any `Image Hash` columns on that row, so the hash gets recalculated for the new image.

`Unique ID` columns can't be edited. A new printing is saved with a blank one, so run `generate-unique-ids` afterwards. A new card gets its Unique ID straight away, in the same form `generate-unique-ids` would give it, because its printings and references are linked to it by that ID.

## Saving
Nothing is written until you save, and only the rows you changed are rewritten. A new printing goes beside the other printings with the same `Card ID` (plain before foils), or into `Card ID` order if it's the first with that ID.

If `card.csv` or `card-printing.csv` changes on disk while the script is open - you switched branch, or saved it from a spreadsheet - the script refuses to save over it and lists the edits so you can redo them.

## How the code is laid out
`main.py` only reads the arguments and runs the search loop. The `Editor` in `editor.py` holds the CSVs and the open card, shows the card both ways and saves it; what can be done to each part of a card is in its own module, mixed into the `Editor`:

| Module | What's in it |
| --- | --- |
| `fields.py` | Showing and editing a row's fields, and carrying a change to the card's other pitches |
| `lists.py` | The lookup CSV behind a column (`Vocabulary`) and the on-screen list a value is picked from |
| `printings.py` | The card's `card-printing.csv` rows, and set printing lookups |
| `references.py` | The card's `card-reference.csv` rows |
| `search.py` | Finding a card by name or print code |
| `csv_io.py` | Reading and writing the CSVs (`Table`) and working copies of rows (`Record`) |
| `screen.py` | The arrow key screen |
| `prompts.py`, `text.py` | Asking for a value on a line or in `$EDITOR`; matching and laying out text |

## Running the Script with System Python

### Initial Setup
1. Ensure your system python is the same version as or compatible with the python version listed in `.python-version`

The script only uses the standard library, so there are no packages to install.

### Running the Script
1. Run `python main.py` to open the card editor.

## Running the Script with Pyenv

### Initial Setup
1. Install [pyenv](https://github.com/pyenv/pyenv).
2. Run `pyenv install` to install Python version.
3. Install [poetry](https://python-poetry.org/).
    * I recommend using `pyenv exec pip install poetry`.
4. Run `pyenv exec poetry install` to install packages.

### Running the Script
1. Run `pyenv exec poetry run python main.py` to open the card editor.
