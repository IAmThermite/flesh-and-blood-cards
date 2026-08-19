"""
A small client for the  database behind cardvault.fabtcg.com.

advanced-search/?set_code=IAR&page_size=500&page=1
    A page of card rows for a set.

card_id/<slug>/
    Everything known about a single card: the shared `cores` (name, stats, text, types)
    plus a `card_prints` list covering every printing in every language and every set in every finish.
"""

import gzip
import json
import time
import urllib.error
import urllib.request

BASE_URL = "https://api.cardvault.fabtcg.com/carddb/api/v1"

# The site the API sits behind, for linking a report entry to the card someone has to read.
SITE_URL = "https://cardvault.fabtcg.com"

# The API doesn't care what the User-Agent is - it answers a bare urllib request happily -
# so say who we actually are rather than pretending to be a browser. If this ever needs rate
# limiting or blocking, whoever runs the API can see what it is and where it came from.
USER_AGENT = "flesh-and-blood-cards/1.0 (+https://github.com/the-fab-cube/flesh-and-blood-cards)"

PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 30
RETRY_DELAYS_SECONDS = [1, 3, 10]

REQUEST_DELAY_SECONDS = 0.25


def card_url(card_id, print_id):
    """
    Where a person can go and look at the printing.

    card_id is the slug the API indexes a card by - "driving-blade-1" - and print_id the set
    number as CardVault writes it, treatment suffix and all, so 1HP171 and MPW134-MV both
    land on the right page. The site is a single page app that routes these in the browser,
    so every one of them answers a plain GET with a 404 and the empty shell; the only way to
    tell a good link from a bad one is to open it.
    """

    return f"{SITE_URL}/card/{card_id}/{print_id}"


class CardVaultError(Exception):
    """Raised when the API can't be reached or returns something unusable."""


def _read_body(response):
    body = response.read()
    if response.headers.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return body.decode("utf-8")


def _get_json(url):
    """GET a URL and parse it as JSON, retrying a few times on transient failures."""

    last_error = None

    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        if attempt > 0:
            time.sleep(RETRY_DELAYS_SECONDS[attempt - 1])

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(_read_body(response))
        except urllib.error.HTTPError as error:
            # 404 means the card genuinely isn't there; retrying won't help. Anything else
            # (429, 5xx) is worth another go.
            if error.code == 404:
                raise CardVaultError(f"404 Not Found: {url}") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error

    raise CardVaultError(f"Gave up on {url} after {len(RETRY_DELAYS_SECONDS) + 1} attempts: {last_error}")


def search_set(set_code):
    """
    Return every published card row for a set, following pagination.

    Note that a "row" here is a card, not a printing - the search response collapses the
    language variants of a printing into a single `languages` mapping.
    """

    rows = []
    page = 1

    while True:
        url = f"{BASE_URL}/advanced-search/?set_code={set_code}&page_size={PAGE_SIZE}&page={page}"
        payload = _get_json(url)

        results = payload.get("results") or []
        rows.extend(results)

        if not payload.get("next") or not results:
            break

        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    return rows


def get_card(card_slug):
    """Return the full record for a single card, or None if the API doesn't have it."""

    time.sleep(REQUEST_DELAY_SECONDS)

    try:
        payload = _get_json(f"{BASE_URL}/card_id/{card_slug}/")
    except CardVaultError:
        return None

    results = payload.get("results") or []
    return results[0] if results else None
