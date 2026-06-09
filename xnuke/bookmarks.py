from playwright.sync_api import Page

from .common import (
    click_confirm,
    click_menu_item_by_text,
    fast_pause,
    human_pause,
    maybe_backoff,
    safe_goto,
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

    deleted = 0
    consecutive_empty = 0
    reload_attempted = False
    for _ in range(max_steps):
        if maybe_backoff(page):
            continue

        rm = page.locator('button[data-testid="removeBookmark"]').first
        try:
            if rm.count() == 0:
                # Only do the body-text empty-state check when there's nothing visible.
                try:
                    body = page.locator("body").inner_text(timeout=4000).lower()
                except Exception:
                    body = ""
                if "you haven't added any bookmarks" in body or "no bookmarks yet" in body:
                    info("No more bookmarks visible.")
                    break

                consecutive_empty += 1
                if consecutive_empty >= 3:
                    if reload_attempted:
                        info("No remove-bookmark buttons after reload — bookmarks are done.")
                        break
                    info("No remove-bookmark buttons; reloading once to verify.")
                    safe_goto(page, url)
                    consecutive_empty = 0
                    reload_attempted = True
                    continue
                short_pause()
                continue

            rm.click(timeout=4000)
            fast_pause()
        except Exception as e:
            warn(f"Bookmark remove failed: {e}")
            short_pause()
            continue

        consecutive_empty = 0
        reload_attempted = False
        deleted += 1
        if deleted % 25 == 0:
            progress("bookmarks", deleted)

    progress("bookmarks", deleted)
    return deleted
