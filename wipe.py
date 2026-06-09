#!/usr/bin/env python3
"""x-nuke: scorched-earth deletion of your own X/Twitter content.

Usage:
    python wipe.py login
    python wipe.py tweets    --yes-really-delete
    python wipe.py likes     --yes-really-delete
    python wipe.py bookmarks --yes-really-delete
    python wipe.py dms       --yes-really-delete
    python wipe.py lists     --yes-really-delete
    python wipe.py all       --yes-really-delete

Dry-run (no destructive action; just verifies login + handle):
    python wipe.py status
"""

from __future__ import annotations

import argparse
import sys

from xnuke.log import info, err, log_path
from xnuke.safety import require_typed_confirmation
from xnuke.session import browser, first_page, is_logged_in, handle_from_session


# Categories that `all` expands to when run sequentially in a single process.
CATEGORIES = ("tweets", "likes", "bookmarks", "dms", "lists")

# Extra single-pass subcommands so parallel runners can split tweets into two tabs.
EXTRA_CATEGORIES = ("tweets-posts", "tweets-replies")


def _browser_kwargs(args: argparse.Namespace) -> dict:
    return {
        "cdp_url": getattr(args, "cdp", None),
        "browser_name": getattr(args, "browser", None),
        "profile_dir": getattr(args, "profile_dir", None),
        "browser_binary": getattr(args, "browser_binary", None),
    }


def _add_browser_flags(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--cdp",
        metavar="URL",
        help="Attach to an already-running Chromium-based browser via CDP, "
             "e.g. http://localhost:9222. Works with Chrome, Brave, Edge, etc. "
             "Browser must have been launched with --remote-debugging-port=9222.",
    )
    sp.add_argument(
        "--browser",
        choices=("chrome", "brave", "edge"),
        help="Launch your real system browser with its real profile "
             "(reads cookies/login). The browser must be fully quit first.",
    )
    sp.add_argument(
        "--profile-dir",
        metavar="PATH",
        help="Override the user-data-dir used with --browser.",
    )
    sp.add_argument(
        "--browser-binary",
        metavar="PATH",
        help="Override the executable used with --browser (e.g. a non-standard Brave install).",
    )


def _interactive_login(page) -> bool:
    """Send to /login and wait (up to 10 min) for a logged-in state."""
    page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=45000)
    info("Waiting up to 10 minutes for login to complete...")
    try:
        page.wait_for_selector(
            'a[data-testid="AppTabBar_Home_Link"], div[data-testid="primaryColumn"]',
            timeout=10 * 60 * 1000,
        )
        return True
    except Exception:
        return False


def cmd_login(args: argparse.Namespace) -> int:
    info("Opening browser. Log in to x.com, then return to this terminal.")
    with browser(headless=False, **_browser_kwargs(args)) as ctx:
        page = first_page(ctx, fresh=bool(args.cdp))
        if not _interactive_login(page):
            err("Did not detect a logged-in state within 10 minutes.")
            return 2
        handle = handle_from_session(page)
        info(f"Logged in as @{handle}. Session saved.")
        return 0


def cmd_status(args: argparse.Namespace) -> int:
    with browser(headless=False, **_browser_kwargs(args)) as ctx:
        page = first_page(ctx, fresh=bool(args.cdp))
        if not is_logged_in(page):
            err("Not logged in. Run: python wipe.py login")
            return 2
        handle = handle_from_session(page)
        info(f"Logged in as @{handle}. Log file: {log_path()}")
        return 0


def cmd_debug(args: argparse.Namespace) -> int:
    """Open the with_replies page, bring it to front, and dump a screenshot + DOM snapshot."""
    from xnuke.common import dump_diagnostics, safe_goto
    with browser(headless=False, **_browser_kwargs(args)) as ctx:
        page = first_page(ctx, fresh=bool(args.cdp))
        if not is_logged_in(page):
            err("Not logged in. Run: python wipe.py login")
            return 2
        handle = handle_from_session(page)
        target = args.url or f"https://x.com/{handle}/with_replies"
        info(f"Debug: navigating to {target}")
        safe_goto(page, target)
        # Give X a generous window to render the timeline.
        try:
            page.wait_for_selector(
                'article[data-testid="tweet"], div[data-testid="cellInnerDiv"]',
                timeout=15000,
            )
            info("Found tweet/cellInnerDiv element on the page.")
        except Exception:
            info("Did NOT find tweet/cellInnerDiv element after 15s.")
        dump_diagnostics(page, "debug")
        return 0


def _run_category(name: str, page) -> int:
    if name == "tweets":
        from xnuke.tweets import wipe_tweets
        return wipe_tweets(page)
    if name == "tweets-posts":
        from xnuke.tweets import wipe_tweets_posts
        return wipe_tweets_posts(page)
    if name == "tweets-replies":
        from xnuke.tweets import wipe_tweets_replies
        return wipe_tweets_replies(page)
    if name == "likes":
        from xnuke.likes import wipe_likes
        return wipe_likes(page)
    if name == "bookmarks":
        from xnuke.bookmarks import wipe_bookmarks
        return wipe_bookmarks(page)
    if name == "dms":
        from xnuke.dms import wipe_dms
        return wipe_dms(page)
    if name == "lists":
        from xnuke.lists import wipe_lists
        return wipe_lists(page)
    raise ValueError(f"Unknown category: {name}")


def _run(category: str, args: argparse.Namespace) -> int:
    if not args.yes_really_delete:
        err("Refusing to run without --yes-really-delete.")
        return 2

    targets = CATEGORIES if category == "all" else (category,)
    label = ", ".join(targets)
    if not args.force:
        if not require_typed_confirmation(label):
            err("Confirmation phrase did not match. Aborting.")
            return 2

    info(f"Starting destructive run for: {label}")
    info(f"Log: {log_path()}")

    with browser(headless=False, **_browser_kwargs(args)) as ctx:
        page = first_page(ctx, fresh=bool(args.cdp))
        try:
            if not is_logged_in(page):
                info("Not logged in — opening login flow.")
                if not _interactive_login(page):
                    err("Did not detect a logged-in state within 10 minutes.")
                    return 2

            for cat in targets:
                try:
                    n = _run_category(cat, page)
                    info(f"Done: {cat} ({n} actions).")
                except Exception as e:
                    err(f"{cat} failed: {e}")
                    # Continue to next category rather than aborting the whole run.
        finally:
            # In CDP mode, close the tab we created so it doesn't linger in the user's browser.
            if args.cdp:
                try:
                    page.close()
                except Exception:
                    pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wipe",
        description="Scorched-earth deletion of your own X/Twitter content.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    login_sp = sub.add_parser("login", help="Open browser to log in. Session is persisted.")
    _add_browser_flags(login_sp)

    status_sp = sub.add_parser("status", help="Verify login + show detected handle.")
    _add_browser_flags(status_sp)

    debug_sp = sub.add_parser(
        "debug",
        help="Open a URL, take a screenshot, and dump DOM diagnostics to logs/.",
    )
    debug_sp.add_argument("--url", help="Override the URL to inspect (default: /<handle>/with_replies).")
    _add_browser_flags(debug_sp)

    for cat in (*CATEGORIES, *EXTRA_CATEGORIES, "all"):
        if cat == "all":
            help_text = "Delete everything (all categories)."
        elif cat == "tweets-posts":
            help_text = "Delete posts + reposts only (the /<handle> tab)."
        elif cat == "tweets-replies":
            help_text = "Delete replies only (the /<handle>/with_replies tab)."
        else:
            help_text = f"Delete all {cat}."
        sp = sub.add_parser(cat, help=help_text)
        sp.add_argument(
            "--yes-really-delete",
            action="store_true",
            help="Required. Without this flag, the command refuses to run.",
        )
        sp.add_argument(
            "--force",
            action="store_true",
            help="Skip the typed 'DELETE EVERYTHING' confirmation. Also auto-runs login if needed.",
        )
        _add_browser_flags(sp)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "login":
        return cmd_login(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "debug":
        return cmd_debug(args)
    if args.cmd in (*CATEGORIES, *EXTRA_CATEGORIES, "all"):
        return _run(args.cmd, args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
