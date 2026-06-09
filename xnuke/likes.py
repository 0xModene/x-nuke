from playwright.sync_api import Page

from .common import (
    click_confirm,
    maybe_backoff,
    safe_goto,
    short_pause,
    very_fast_pause,
)
from .log import info, warn, progress
from .session import handle_from_session


def _maybe_confirm(page: Page) -> None:
    """X occasionally pops a confirmation modal on unlike (sensitive-content prompts).
    Almost always absent — peek for it with a tiny timeout and click only if present."""
    try:
        page.wait_for_selector(
            '[data-testid="confirmationSheetConfirm"], [data-testid="confirmationSheetDelete"]',
            timeout=200,
        )
    except Exception:
        return
    click_confirm(page)


def _is_likes_empty(page: Page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=4000).lower()
    except Exception:
        return False
    return "haven't liked" in body or "hasn't liked" in body


def wipe_likes(page: Page, max_steps: int = 200000) -> int:
    handle = handle_from_session(page)
    if not handle:
        raise RuntimeError("Could not determine logged-in handle. Run `login` first.")

    url = f"https://x.com/{handle}/likes"
    info(f"Wiping likes for @{handle}")
    safe_goto(page, url)

    deleted = 0
    consecutive_empty = 0
    reload_attempted = False
    for _ in range(max_steps):
        if maybe_backoff(page):
            continue

        unlike = page.locator('button[data-testid="unlike"]').first
        try:
            if unlike.count() == 0:
                if _is_likes_empty(page):
                    info("No more likes visible.")
                    break
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    if reload_attempted:
                        info("No unlike buttons after reload — likes are done.")
                        break
                    info("No unlike buttons; reloading once to verify.")
                    safe_goto(page, url)
                    consecutive_empty = 0
                    reload_attempted = True
                    continue
                short_pause()
                continue

            unlike.click(timeout=4000)
            _maybe_confirm(page)
            very_fast_pause()
        except Exception as e:
            warn(f"Unlike attempt failed: {e}")
            short_pause()
            continue

        consecutive_empty = 0
        reload_attempted = False
        deleted += 1
        if deleted % 25 == 0:
            progress("likes", deleted)

    progress("likes", deleted)
    return deleted
