from playwright.sync_api import Page

from .common import (
    click_confirm,
    click_menu_item_by_text,
    fast_pause,
    human_pause,
    maybe_backoff,
    safe_goto,
    scroll_a_bit,
    short_pause,
)
from .log import info, warn, progress


def _try_clear_all(page) -> bool:
    """Use the 'Clear all Bookmarks' overflow option if present."""
    # Open page header menu
    try:
        menu = page.locator('button[aria-label="More"]').first
        if menu.count() == 0:
            return False
        menu.click(timeout=4000)
    except Exception:
        return False

    short_pause()
    label = click_menu_item_by_text(page, "Clear all Bookmarks", "Clear all bookmarks")
    if not label:
        page.keyboard.press("Escape")
        return False

    short_pause()
    return click_confirm(page)


def wipe_bookmarks(page: Page, max_steps: int = 100000) -> int:
    url = "https://x.com/i/bookmarks"
    info("Wiping bookmarks")
    safe_goto(page, url)

    if _try_clear_all(page):
        info("Used 'Clear all Bookmarks'.")
        human_pause()
        return -1  # sentinel: bulk clear used

    # Phrases X has used to mean "no bookmarks here".
    empty_phrases = (
        "you haven't added any bookmarks",
        "no bookmarks yet",
        "no bookmarks here",
        "save posts for later",
    )

    deleted = 0
    no_progress_streak = 0  # iterations since the last successful delete

    for _ in range(max_steps):
        if maybe_backoff(page):
            continue

        rm = page.locator('button[data-testid="removeBookmark"]').first
        if rm.count() > 0:
            try:
                rm.click(timeout=4000)
                fast_pause()
            except Exception as e:
                warn(f"Bookmark remove failed: {e}")
                no_progress_streak += 1
                short_pause()
                continue
            no_progress_streak = 0
            deleted += 1
            if deleted % 25 == 0:
                progress("bookmarks", deleted)
            continue

        # No remove-buttons visible — check empty state, scroll to load more,
        # and bail out after a few cycles with no progress.
        try:
            body = page.locator("body").inner_text(timeout=4000).lower()
        except Exception:
            body = ""
        if any(p in body for p in empty_phrases):
            info("No more bookmarks visible.")
            break

        scroll_a_bit(page, 1500)
        no_progress_streak += 1
        short_pause()

        if no_progress_streak >= 6:
            info("No remove-bookmark buttons after scrolling — bookmarks are done.")
            break

    progress("bookmarks", deleted)
    return deleted
