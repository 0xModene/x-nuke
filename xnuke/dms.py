from playwright.sync_api import Page

from .common import (
    click_confirm,
    dump_diagnostics,
    human_pause,
    maybe_backoff,
    safe_goto,
    short_pause,
)
from .log import info, warn, progress

DM_URL = "https://x.com/messages"

EMPTY_HINTS = (
    "welcome to your inbox",
    "you have no messages",
    "no conversations",
    "start a new chat",
)

# X Chat selectors, confirmed working as of 2026-06-09.
CONVERSATION_SELECTOR = '[data-testid^="dm-conversation-item-"]'
INBOX_PANEL = '[data-testid="dm-inbox-panel"]'


def _find_first_conversation(page: Page):
    loc = page.locator(CONVERSATION_SELECTOR).first
    try:
        if loc.count() > 0 and loc.is_visible():
            return loc
    except Exception:
        pass
    return None


def _delete_via_context_menu(page: Page, row) -> bool:
    """Right-click the row to open X Chat's custom popover, click 'Delete conversation'
    (1:1 DMs) or 'Leave conversation' (group chats), then confirm. Verifies the row
    actually detaches from the DOM before reporting success."""
    try:
        row_testid = row.get_attribute("data-testid", timeout=2000)
    except Exception:
        row_testid = None

    try:
        row.scroll_into_view_if_needed(timeout=3000)
        row.click(button="right", timeout=4000)
    except Exception:
        return False

    action_text = None
    for candidate in ("Delete conversation", "Leave conversation"):
        try:
            page.wait_for_selector(f'text="{candidate}"', timeout=1500)
            action_text = candidate
            break
        except Exception:
            continue
    if action_text is None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    click_targets = (
        f'text="{action_text}"',
        f'[role="menuitem"]:has-text("{action_text}")',
        f'div:has-text("{action_text}")',
    )
    clicked = False
    for sel in click_targets:
        loc = page.locator(sel).first
        try:
            if loc.count() == 0:
                continue
            loc.click(timeout=3000)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    short_pause()
    if not click_confirm(page):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    if row_testid:
        try:
            page.wait_for_selector(
                f'[data-testid="{row_testid}"]',
                state="detached",
                timeout=6000,
            )
        except Exception:
            return False

    human_pause()
    return True


def wipe_dms(page: Page, max_steps: int = 100000) -> int:
    info("Wiping DMs")
    safe_goto(page, DM_URL)
    try:
        page.wait_for_selector(INBOX_PANEL, timeout=10000)
    except Exception:
        pass

    deleted = 0
    consecutive_empty = 0
    stuck_reloads = 0
    dumped = False

    for _ in range(max_steps):
        if maybe_backoff(page):
            continue

        try:
            body = page.locator("body").inner_text(timeout=5000).lower()
        except Exception:
            body = ""
        if any(h in body for h in EMPTY_HINTS):
            break

        row = _find_first_conversation(page)
        if row is None:
            consecutive_empty += 1
            short_pause()
            if consecutive_empty >= 3:
                if not dumped:
                    dump_diagnostics(page, "dms-stuck")
                    dumped = True
                safe_goto(page, DM_URL)
                consecutive_empty = 0
                stuck_reloads += 1
                if stuck_reloads >= 3:
                    warn(
                        "Aborting DMs: 3 reloads with no conversation row. "
                        "Selectors may have changed — see logs/diag-dms-stuck-*.png."
                    )
                    break
            continue

        if _delete_via_context_menu(page, row):
            consecutive_empty = 0
            stuck_reloads = 0
            deleted += 1
            if deleted % 5 == 0:
                progress("dms", deleted)
            try:
                page.wait_for_selector(INBOX_PANEL, timeout=6000)
            except Exception:
                safe_goto(page, DM_URL)
        else:
            consecutive_empty += 1
            safe_goto(page, DM_URL)
            if consecutive_empty >= 5:
                warn("Aborting DMs: too many consecutive delete failures.")
                break

    progress("dms", deleted)
    return deleted
