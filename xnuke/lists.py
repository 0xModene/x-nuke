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


def _open_first_owned_list(page) -> bool:
    # On /<handle>/lists, the "Lists you own" section comes first.
    # Each list row is a link to /i/lists/<id>.
    rows = page.locator('a[href*="/i/lists/"]')
    if rows.count() == 0:
        return False
    try:
        rows.first.scroll_into_view_if_needed(timeout=4000)
        rows.first.click(timeout=5000)
        return True
    except Exception as e:
        warn(f"Could not open list: {e}")
        return False


def _delete_open_list(page) -> bool:
    # Open the list overflow menu in the header.
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
        page.keyboard.press("Escape")
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
    consecutive_empty = 0
    for _ in range(max_steps):
        if maybe_backoff(page):
            continue

        if not _open_first_owned_list(page):
            consecutive_empty += 1
            if consecutive_empty >= 3:
                info("No more lists found.")
                break
            short_pause()
            continue

        short_pause()
        ok = _delete_open_list(page)
        if not ok:
            warn("Could not delete the open list; returning to lists page.")
            safe_goto(page, url)
            continue

        consecutive_empty = 0
        deleted += 1
        progress("lists", deleted)

        try:
            page.wait_for_url("**/lists**", timeout=8000)
        except Exception:
            safe_goto(page, url)

    progress("lists", deleted)
    return deleted
