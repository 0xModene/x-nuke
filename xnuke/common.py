import random
import time
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import Page, TimeoutError as PWTimeout

from .log import info, warn, log_path

DIAG_DIR = log_path().parent

# Jitter between destructive actions (seconds).
ACTION_MIN = 1.4
ACTION_MAX = 3.2

# When X surfaces a rate-limit signal, sleep this long before retrying.
RATE_LIMIT_BACKOFF = 5 * 60


def human_pause() -> None:
    time.sleep(random.uniform(ACTION_MIN, ACTION_MAX))


def short_pause() -> None:
    time.sleep(random.uniform(0.4, 0.9))


def fast_pause() -> None:
    """Tighter pacing for single-click actions with no confirmation step (likes, bookmarks)."""
    time.sleep(random.uniform(0.5, 1.0))


def very_fast_pause() -> None:
    """Aggressive pacing for the simplest single-click flows. Will hit X's hourly rate-limit
    sooner, but the script's 5-min backoff handles that gracefully."""
    time.sleep(random.uniform(0.2, 0.5))


def detect_rate_limit(page: Page) -> bool:
    """Best-effort detection of X rate-limit / 'something went wrong' banners."""
    selectors = [
        'div:has-text("Rate limit exceeded")',
        'div:has-text("Too many requests")',
        'div:has-text("Something went wrong. Try reloading")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


def maybe_backoff(page: Page) -> bool:
    if detect_rate_limit(page):
        warn(f"Rate-limit indicator detected. Sleeping {RATE_LIMIT_BACKOFF}s.")
        time.sleep(RATE_LIMIT_BACKOFF)
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        return True
    return False


def click_menu_item_by_text(page: Page, *candidates: str) -> str | None:
    """Click the first matching menuitem by text. Returns the matched label or None."""
    for label in candidates:
        loc = page.locator(f'div[role="menuitem"]:has-text("{label}")')
        try:
            if loc.count() > 0:
                loc.first.click(timeout=4000)
                return label
        except Exception:
            continue
    return None


def click_confirm(page: Page) -> bool:
    """Click the confirm button in the modal sheet. Tries the standard X testid first,
    then a few fallbacks for variants like the DM-delete confirmation."""
    selectors = (
        '[data-testid="confirmationSheetConfirm"]',
        '[data-testid="confirmationSheetDelete"]',
        '[data-testid="confirmationSheetPrimaryButton"]',
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=3000)
                return True
        except PWTimeout:
            continue
        except Exception:
            continue
    # Fallback: a button labeled Delete/Confirm/Leave inside an open dialog or alertdialog.
    for txt in ("Confirm", "Delete", "Yes, delete", "Leave", "Yes, leave"):
        try:
            btn = page.locator(
                f'div[role="dialog"] button:has-text("{txt}"), '
                f'div[role="alertdialog"] button:has-text("{txt}")'
            ).first
            if btn.count() > 0:
                btn.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


def scroll_a_bit(page: Page, px: int = 600) -> None:
    page.mouse.wheel(0, px)


def safe_goto(page: Page, url: str) -> None:
    try:
        page.bring_to_front()
    except Exception:
        pass
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    short_pause()
    maybe_backoff(page)


def dump_diagnostics(page: Page, label: str) -> None:
    """Save a screenshot + a short HTML snippet so we can see what the page actually looks like."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = DIAG_DIR / f"diag-{label}-{ts}"
    try:
        page.screenshot(path=str(base) + ".png", full_page=False)
        info(f"Diagnostic screenshot: {base}.png")
    except Exception as e:
        warn(f"Could not save screenshot: {e}")
    try:
        html = page.content()
        Path(str(base) + ".html").write_text(html, encoding="utf-8")
        info(f"Diagnostic HTML: {base}.html")
    except Exception as e:
        warn(f"Could not save HTML: {e}")
    try:
        # Every distinct data-testid on the page.
        testids = page.evaluate(
            "() => Array.from(new Set(Array.from(document.querySelectorAll('[data-testid]'))"
            ".map(e => e.getAttribute('data-testid')))).sort()"
        )
        info(f"Visible data-testid count: {len(testids)}")
        # Surface the ones likeliest to be relevant.
        keywords = (
            "tweet", "cell", "tab", "primary", "caret", "menu",
            "messag", "chat", "inbox", "dm", "conv", "thread",
        )
        for t in testids:
            if any(k in t.lower() for k in keywords):
                info(f"  testid: {t}")
        # Also dump the complete testid list to a sidecar file so we can grep it.
        Path(str(base) + ".testids.txt").write_text("\n".join(testids), encoding="utf-8")
        info(f"All testids written to: {base}.testids.txt")
    except Exception as e:
        warn(f"Could not enumerate testids: {e}")
    try:
        # Hrefs leaving the current path — strong hint for what's clickable in lists.
        hrefs = page.evaluate(
            "() => Array.from(new Set(Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => a.getAttribute('href')).filter(h => h && !h.startsWith('#'))))"
            ".slice(0, 200)"
        )
        Path(str(base) + ".hrefs.txt").write_text("\n".join(hrefs), encoding="utf-8")
        info(f"Sample hrefs written to: {base}.hrefs.txt")
    except Exception as e:
        warn(f"Could not enumerate hrefs: {e}")


def with_retries(fn, *, attempts: int = 3, label: str = ""):
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            warn(f"{label} attempt {i}/{attempts} failed: {e}")
            time.sleep(2 * i)
    if last:
        raise last
