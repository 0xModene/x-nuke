import os
import sys
from pathlib import Path
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, BrowserContext, Page

from .log import info, warn

SESSION_DIR = Path(__file__).resolve().parent.parent / ".session"
SESSION_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
)


def _local_appdata() -> Path:
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local)


def _default_chrome_profile() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    if sys.platform.startswith("linux"):
        return Path.home() / ".config" / "google-chrome"
    if sys.platform.startswith("win"):
        return _local_appdata() / "Google" / "Chrome" / "User Data"
    return SESSION_DIR


def _default_brave_profile() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser"
    if sys.platform.startswith("linux"):
        return Path.home() / ".config" / "BraveSoftware" / "Brave-Browser"
    if sys.platform.startswith("win"):
        return _local_appdata() / "BraveSoftware" / "Brave-Browser" / "User Data"
    return SESSION_DIR


def _default_edge_profile() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Microsoft Edge"
    if sys.platform.startswith("linux"):
        return Path.home() / ".config" / "microsoft-edge"
    if sys.platform.startswith("win"):
        return _local_appdata() / "Microsoft" / "Edge" / "User Data"
    return SESSION_DIR


def _brave_executable() -> Path | None:
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates += [
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            Path.home() / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
    elif sys.platform.startswith("linux"):
        candidates += [
            Path("/usr/bin/brave-browser"),
            Path("/usr/bin/brave"),
            Path("/snap/bin/brave"),
            Path("/opt/brave.com/brave/brave-browser"),
        ]
    elif sys.platform.startswith("win"):
        for root in (
            _local_appdata() / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            Path("C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"),
            Path("C:/Program Files (x86)/BraveSoftware/Brave-Browser/Application/brave.exe"),
        ):
            candidates.append(root)
    for c in candidates:
        if c.exists():
            return c
    return None


def _browser_spec(name: str) -> dict:
    name = name.lower()
    if name == "chrome":
        return {"channel": "chrome", "default_profile": _default_chrome_profile(), "pretty": "Google Chrome"}
    if name == "edge":
        return {"channel": "msedge", "default_profile": _default_edge_profile(), "pretty": "Microsoft Edge"}
    if name == "brave":
        exe = _brave_executable()
        if exe is None:
            raise RuntimeError(
                "Could not find Brave Browser. Install it from https://brave.com/, or pass "
                "--browser-binary /path/to/Brave to point at it explicitly."
            )
        return {"executable_path": exe, "default_profile": _default_brave_profile(), "pretty": "Brave"}
    raise ValueError(f"Unknown browser: {name}. Expected: chrome | brave | edge.")


# Back-compat — kept so old code/scripts still import a working path.
default_chrome_profile_dir = _default_chrome_profile


@contextmanager
def browser(
    *,
    headless: bool = False,
    cdp_url: str | None = None,
    browser_name: str | None = None,
    profile_dir: Path | None = None,
    browser_binary: Path | None = None,
):
    with sync_playwright() as p:
        # Mode A: attach to an already-running Chromium-based browser over CDP.
        if cdp_url:
            info(f"Attaching to existing browser over CDP: {cdp_url}")
            brw = p.chromium.connect_over_cdp(cdp_url)
            ctx = brw.contexts[0] if brw.contexts else brw.new_context()
            try:
                yield ctx
            finally:
                info("Disconnecting from CDP (your browser stays open).")
                try:
                    brw.close()
                except Exception:
                    pass
            return

        # Mode B: launch your real browser (chrome | brave | edge) with your real profile.
        if browser_name:
            spec = _browser_spec(browser_name)
            udd = Path(profile_dir) if profile_dir else spec["default_profile"]
            info(f"Launching {spec['pretty']} with profile: {udd}")
            if not udd.exists():
                warn(f"Profile dir does not exist yet — it will be created: {udd}")
            launch_kwargs = dict(
                user_data_dir=str(udd),
                headless=headless,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            if browser_binary:
                launch_kwargs["executable_path"] = str(browser_binary)
            elif "executable_path" in spec:
                launch_kwargs["executable_path"] = str(spec["executable_path"])
            if "channel" in spec and "executable_path" not in launch_kwargs:
                launch_kwargs["channel"] = spec["channel"]
            try:
                ctx = p.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to launch {spec['pretty']}. Most likely it's already running "
                    f"and has the profile locked — fully quit it (Cmd+Q on macOS), then retry.\n"
                    f"Underlying error: {e}"
                ) from e
            try:
                yield ctx
            finally:
                info(f"Closing {spec['pretty']}.")
                try:
                    ctx.close()
                except Exception:
                    pass
            return

        # Default: isolated Playwright Chromium with a saved x-nuke profile.
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield ctx
        finally:
            info("Closing browser context.")
            ctx.close()


def first_page(ctx: BrowserContext, *, fresh: bool = False) -> Page:
    if fresh or not ctx.pages:
        return ctx.new_page()
    return ctx.pages[0]


def is_logged_in(page: Page) -> bool:
    page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector(
            'a[data-testid="AppTabBar_Home_Link"], div[data-testid="primaryColumn"]',
            timeout=8000,
        )
        return True
    except Exception:
        return False


def handle_from_session(page: Page) -> str | None:
    """Read the logged-in user's @handle from the side nav."""
    try:
        page.wait_for_selector('a[data-testid="AppTabBar_Profile_Link"]', timeout=10000)
        href = page.get_attribute('a[data-testid="AppTabBar_Profile_Link"]', "href")
        if href and href.startswith("/"):
            return href.lstrip("/")
    except Exception:
        pass
    return None
