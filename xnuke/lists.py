import re

from playwright.sync_api import Page

from .common import (
    click_confirm,
    click_menu_item_by_text,
    human_pause,
    maybe_backoff,
    safe_goto,
    short_pause,
)
from .log import info, warn, progress
from .session import handle_from_session

# /<handle>/lists shows BOTH your owned lists AND lists you follow. We can only
# delete the ones you own, so track ids we've tried and failed (don't own) to
# avoid re-opening them in an infinite loop.
LIST_HREF_RE = re.compile(r"/i/lists/(\d+)")


def _list_id_from_href(href: str) -> str | None:
    m = LIST_HREF_RE.search(href)
    return m.group(1) if m else None


def _find_next_unprocessed_list(page: Page, skipped_ids: set[str]):
    """Return (locator, list_id) for the first list row whose id is not in skipped_ids."""
    rows = page.locator('a[href*="/i/lists/"]').all()
    for row in rows:
        try:
            href = row.get_attribute("href", timeout=1500)
        except Exception:
            continue
        if not href:
            continue
        list_id = _list_id_from_href(href)
        if list_id is None or list_id in skipped_ids:
            continue
        return row, list_id
    return None, None


def _delete_open_list(page: Page) -> bool:
    """With a list page open, try to open the overflow menu and click Delete list.
    Returns False if the menu has no Delete option (i.e. we don't own this list)."""
    btn = page.locator('button[aria-label="List menu"], button[aria-label="More"]').first
    if btn.count() == 0:
        return False
    try:
        btn.click(timeout=4000)
    except Exception:
        return False

    short_pause()
    label = click_menu_item_by_text(page, "Delete list", "Delete List")
    if not label:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    short_pause()
    click_confirm(page)
    human_pause()
    return True


def wipe_lists(page: Page, max_steps: int = 5000) -> int:
    handle = handle_from_session(page)
    if not handle:
        raise RuntimeError("Could not determine logged-in handle. Run `login` first.")

    url = f"https://x.com/{handle}/lists"
    info(f"Wiping owned lists for @{handle}")
    safe_goto(page, url)

    deleted = 0
    skipped_ids: set[str] = set()

    for _ in range(max_steps):
        if maybe_backoff(page):
            continue

        row, list_id = _find_next_unprocessed_list(page, skipped_ids)
        if row is None:
            info("No more deletable lists found.")
            break

        try:
            row.scroll_into_view_if_needed(timeout=4000)
            row.click(timeout=5000)
            page.wait_for_url(f"**/i/lists/{list_id}**", timeout=6000)
        except Exception as e:
            warn(f"Could not open list {list_id}: {e}")
            skipped_ids.add(list_id)
            safe_goto(page, url)
            continue

        short_pause()
        if not _delete_open_list(page):
            # No Delete option in the menu — we don't own this list. Skip it forever.
            skipped_ids.add(list_id)
            safe_goto(page, url)
            continue

        deleted += 1
        progress("lists", deleted)

        try:
            page.wait_for_url("**/lists**", timeout=8000)
        except Exception:
            safe_goto(page, url)

    progress("lists", deleted)
    return deleted
