import time

from playwright.sync_api import Page

from .common import (
    click_confirm,
    dump_diagnostics,
    human_pause,
    maybe_backoff,
    safe_goto,
    scroll_a_bit,
    short_pause,
)
from .log import info, warn, progress
from .session import handle_from_session

EMPTY_STATE_HINTS = (
    "haven't posted",
    "hasn't posted",
    "Nothing to see here",
    "doesn’t exist",
    "doesn't exist",
)

# Substring matches (case-insensitive) for destructive items in an article's caret menu.
# Most specific first so "Delete post" wins over the generic "Delete".
ACTION_LABELS = (
    "Delete post",
    "Delete reply",
    "Delete",
    "Undo repost",
    "Undo Retweet",
    "Unpin from profile",
)


def _is_empty_timeline(page: Page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    return any(h.lower() in body for h in EMPTY_STATE_HINTS)


def _try_undo_repost_via_button(page: Page, art) -> str | None:
    """If this article is a repost YOU made, the action bar has a toggled-on repost button
    with data-testid='unretweet'. Click it, then confirm via data-testid='unretweetConfirm'
    or a menuitem containing 'undo' + 'repost'."""
    btn = art.locator('button[data-testid="unretweet"]').first
    if btn.count() == 0:
        return None
    try:
        btn.scroll_into_view_if_needed(timeout=3000)
        btn.click(timeout=4000)
    except Exception:
        return None

    try:
        page.wait_for_selector(
            '[data-testid="unretweetConfirm"], div[role="menuitem"]',
            timeout=4000,
        )
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return None

    confirm = page.locator('[data-testid="unretweetConfirm"]').first
    if confirm.count() > 0:
        try:
            confirm.click(timeout=3000)
            human_pause()
            return "Undo Repost"
        except Exception:
            pass

    items = page.locator('div[role="menuitem"]').all_text_contents()
    for idx, txt in enumerate(items):
        t = txt.lower()
        if "undo" in t and ("repost" in t or "retweet" in t):
            try:
                page.locator('div[role="menuitem"]').nth(idx).click(timeout=3000)
                human_pause()
                return "Undo Repost"
            except Exception:
                continue

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return None


def _try_caret_action(page: Page, art) -> str | None:
    """Open the article's caret menu and click Delete / Undo repost / Unpin if exposed.
    Returns None if the menu has none of those (i.e. it's someone else's tweet)."""
    caret = art.locator('[data-testid="caret"]').first
    if caret.count() == 0:
        return None
    try:
        caret.scroll_into_view_if_needed(timeout=3000)
        caret.click(timeout=4000)
    except Exception:
        return None

    try:
        page.wait_for_selector('div[role="menuitem"], [role="menuitem"]', timeout=4000)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return None

    items_lc = " | ".join(page.locator('div[role="menuitem"]').all_text_contents()).lower()
    action = None
    for label in ACTION_LABELS:
        if label.lower() not in items_lc:
            continue
        try:
            page.locator(
                f'div[role="menuitem"]:has-text("{label}"), '
                f'[role="menuitem"]:has-text("{label}")'
            ).first.click(timeout=3000)
            action = label
            break
        except Exception:
            continue

    if action is None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(0.25)
        return None

    short_pause()
    if any(k in action.lower() for k in ("delete", "undo", "remove")):
        click_confirm(page)
    human_pause()
    return action


def _try_act_on_article(page: Page, art) -> str | None:
    """Try to delete / undo repost / unpin this one article. Returns the action label,
    or None if the article isn't yours (no Delete/Undo/Unpin in its menu)."""
    result = _try_undo_repost_via_button(page, art)
    if result is not None:
        return result
    return _try_caret_action(page, art)


def _drain_timeline(page: Page, url: str, label: str, max_steps: int) -> int:
    """Walk through the timeline once with a persistent cursor.

    The cursor advances when an article is non-actionable (foreign reply context, etc.)
    and stays put when an article is successfully acted on — because after the
    deletion the DOM shifts, and what was at cursor+1 is now at cursor. This makes
    the cost roughly O(visible_articles) per pass instead of O(visible² × deletes)
    that a restart-from-top loop incurs.

    When the cursor reaches the end of the visible list we scroll; after enough
    stuck scrolls we reload the page and reset the cursor to 0.
    """
    safe_goto(page, url)
    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
    except Exception:
        pass

    deleted = 0
    cursor = 0
    stuck_scrolls = 0
    stuck_reloads = 0
    dumped = False

    for _ in range(max_steps):
        if maybe_backoff(page):
            continue
        if _is_empty_timeline(page):
            break

        articles = page.locator('article[data-testid="tweet"]')
        count = articles.count()

        if cursor >= count:
            scroll_a_bit(page, 800)
            stuck_scrolls += 1
            short_pause()
            if stuck_scrolls >= 6:
                stuck_scrolls = 0
                stuck_reloads += 1
                if not dumped:
                    dump_diagnostics(page, f"{label}-stuck")
                    dumped = True
                if stuck_reloads >= 3:
                    break
                safe_goto(page, url)
                cursor = 0
            continue

        art = articles.nth(cursor)
        try:
            if not art.is_visible():
                cursor += 1
                continue
        except Exception:
            cursor += 1
            continue

        result = _try_act_on_article(page, art)
        if result is not None:
            stuck_scrolls = 0
            stuck_reloads = 0
            deleted += 1
            if deleted % 10 == 0:
                progress(label, deleted, last=result)
            # Stay at cursor — the DOM shifted; the next article is at this index.
        else:
            cursor += 1

    progress(label, deleted)
    return deleted


def _require_handle(page: Page) -> str:
    handle = handle_from_session(page)
    if not handle:
        raise RuntimeError("Could not determine logged-in handle. Run `login` first.")
    return handle


def wipe_tweets_posts(page: Page, max_steps: int = 100000) -> int:
    """Drain only the Posts tab — your originals + reposts. Clean and fast (no foreign
    reply context to walk past)."""
    handle = _require_handle(page)
    info(f"Wiping posts/reposts for @{handle}")
    return _drain_timeline(page, f"https://x.com/{handle}", "tweets[posts]", max_steps)


def wipe_tweets_replies(page: Page, max_steps: int = 100000) -> int:
    """Drain only the Replies tab. Slower per-action because reply chains interleave
    other people's tweets we have to skip past. Misses replies that X hides behind
    "Show this thread" — those are caught by wipe_tweets_search."""
    handle = _require_handle(page)
    info(f"Wiping replies for @{handle}")
    return _drain_timeline(
        page, f"https://x.com/{handle}/with_replies", "tweets[replies]", max_steps
    )


def wipe_tweets_search(page: Page, max_steps: int = 100000) -> int:
    """Drain `from:<handle>` search results. Search lists every tweet you authored as
    flat top-level articles — no thread grouping — so it catches replies buried in
    chains that the Replies tab collapsed behind 'Show this thread' links."""
    handle = _require_handle(page)
    info(f"Wiping search results from:@{handle}")
    return _drain_timeline(
        page,
        f"https://x.com/search?q=from%3A{handle}&src=typed_query&f=live",
        "tweets[search]",
        max_steps,
    )


def wipe_tweets(page: Page, max_steps: int = 100000) -> int:
    """Run all three passes sequentially in the same tab — for non-parallel callers."""
    n_posts = wipe_tweets_posts(page, max_steps)
    n_replies = wipe_tweets_replies(page, max_steps)
    n_search = wipe_tweets_search(page, max_steps)
    total = n_posts + n_replies + n_search
    info(f"tweets total: {total} (posts: {n_posts}, replies: {n_replies}, search: {n_search})")
    return total
