# x-nuke

Scorched-earth deletion of your own X/Twitter content. Drives your real Brave
browser session over Chrome DevTools Protocol, so it acts inside your already
logged-in account — no API keys, no $200/month X subscription.

Deletes, in order:

1. **Tweets** — posts, replies, and reposts (`/<handle>` then `/<handle>/with_replies`)
2. **Likes** — every tweet you've ever liked
3. **Bookmarks** — uses X's "Clear all" when available, otherwise per-row
4. **DMs** — every conversation; uses X Chat's right-click context menu, handles
   both 1:1 "Delete conversation" and group "Leave conversation"
5. **Lists** — every list you own

It does **not** touch follows, followers, blocks, or mutes.

This is **destructive and irreversible.** Run it knowing exactly what it does.

## Quickstart

Prerequisites:

- macOS (Linux mostly works; Windows untested)
- [Brave Browser](https://brave.com/) installed and signed in to your X account
- Python 3.10+

```bash
git clone <YOUR_REPO_URL> x-nuke
cd x-nuke
./nuke.sh
```

That's it. The launcher:

1. Creates a Python virtual env and installs deps (one-time, ~30 s)
2. Installs Playwright's Chromium binary as a fallback (one-time, ~90 s)
3. Restarts Brave with `--remote-debugging-port=9222` so Playwright can attach
   (pauses to let you save work first if Brave is open)
4. Waits for the debug port to come up
5. **Launches 6 wipe processes in parallel**, each in its own Brave tab.
   Tweets is split into two passes — Posts tab (`/<handle>`) and Replies tab
   (`/<handle>/with_replies`) — so each runs alongside likes / bookmarks /
   DMs / lists rather than back-to-back. As each tab finishes — no more
   tweets to delete, no more likes, etc. — it closes itself automatically.
   The whole thing exits when the last tab is done.

Output is prefixed per category so the streams stay readable:

```
[tweets-posts]   Wiping posts/reposts for @your_handle
[tweets-replies] Wiping replies for @your_handle
[likes]          Wiping likes for @your_handle
[bookmarks]      Wiping bookmarks
[dms]            Wiping DMs
[lists]          Wiping owned lists for @your_handle
[likes]          likes: deleted 25
[dms]            dms: deleted 5
[tweets-posts]   tweets[posts]: deleted 10 — last: Delete post
...
```

Ctrl+C kills every child cleanly.

If you're not signed in to x.com in Brave, a tab will open to the login page
and the tool will wait up to 10 minutes for you to finish signing in (handle
2FA normally), then continue automatically.

**Heads-up on parallel mode:** each category's Playwright tab calls
`bring_to_front()` when it navigates, so your Brave focus will jump between
the 5 tabs. Don't try to use Brave for anything else while parallel runs are
active. Also: X rate-limits per *account*, not per tab, so running 5 in
parallel hits the `Too many requests` ceiling sooner — the script's 5-min
backoff kicks in per-tab when that happens.

## Single-category runs

Each of these runs serially in one tab:

```bash
./nuke.sh tweets           # both posts and replies in the same tab, sequentially
./nuke.sh tweets-posts     # just the Posts tab
./nuke.sh tweets-replies   # just the Replies tab
./nuke.sh likes
./nuke.sh bookmarks
./nuke.sh dms
./nuke.sh lists
```

Useful if you only need to wipe one category, or if you want to retry a
single category after a daily rate-limit reset.

Logs for every run go to `logs/<UTC-timestamp>.log`. `tail -F logs/*.log` in a
spare terminal to watch all of them at once.

## What to expect

- **Pacing.** Tweets/DMs use 1.4–3.2 s between actions (multi-step flows with
  confirmation sheets). Likes/bookmarks use 0.2–0.5 s (single-click flows).
- **Rate limits.** When X surfaces "Too many requests" / "Something went
  wrong", the tool sleeps 5 minutes and retries. Hard daily caps (X's hidden
  ~1000 like/unlike per day, etc.) means very heavy accounts may need to be
  run across multiple days — just re-run `./nuke.sh likes`, it'll pick up
  where it left off.
- **DMs.** X only lets you delete a conversation *for you* — the other side
  still sees it. Platform limitation; no automation can change it.
- **Pinned tweets.** Unpinned first, then deleted on the next pass.
- **Reposts.** Detected via the toggled-on `data-testid="unretweet"` button on
  each article; falls back to the caret menu's "Undo Repost" option.
- **Resumability.** Every run picks up wherever the current state is. Stop
  with Ctrl+C and restart freely.

## Logs

Each run writes a timestamped log to `logs/`:

```
logs/20260609-185731.log
logs/diag-tweets-stuck-*.png    # auto-saved screenshots when something gets stuck
logs/diag-dms-open-conv-*.html  # diagnostic DOM dumps from sticky pages
```

The diag files only appear if a category gets stuck mid-run. They're how
you'd debug a future X UI change.

## Manual / advanced usage

If you don't want the launcher, you can still drive it yourself:

```bash
# One-time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Launch your own browser however you like (Brave/Chrome/Edge), with
#   --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1
# pointed at your real profile, then attach:
python wipe.py all --yes-really-delete --force --cdp http://127.0.0.1:9222

# Or skip CDP entirely and let Playwright drive a fresh Chromium with its own
# saved session (login required on first run):
python wipe.py login
python wipe.py all --yes-really-delete --force
```

`wipe.py --help` lists every subcommand and flag.

### Browsers other than Brave

`./nuke.sh` is hardcoded to Brave because that's what the author uses. The
underlying Python tool supports any Chromium-based browser via `--cdp` (CDP
attach to your launched browser), or `--browser chrome|brave|edge` to let
Playwright launch your system browser using your real profile. For
Chrome/Edge, copy `nuke.sh` and change the `BRAVE_BIN` / `BRAVE_PROFILE`
lines, or run the python command directly.

## Project layout

```
nuke.sh                   # one-command launcher (deps, Brave, CDP, wipe)
wipe.py                   # Python CLI
requirements.txt
xnuke/
  session.py              # Playwright browser bootstrapping (CDP / system / Chromium)
  safety.py               # typed-confirmation prompt (skipped by --force)
  log.py                  # stderr + file logging
  common.py               # pacing, rate-limit detection, confirmation helpers
  tweets.py               # posts + replies + reposts deleter
  likes.py
  bookmarks.py
  dms.py                  # X Chat right-click context menu flow
  lists.py
.session/                 # Playwright Chromium user data dir (gitignored)
logs/                     # per-run logs + diagnostics (gitignored)
```

## Known fragility

X's DOM changes. Selectors rely on `data-testid` attributes. If a category
stops making progress and reloads the page repeatedly, it'll auto-dump a
screenshot (`logs/diag-<category>-stuck-*.png`) plus a list of every testid
on the page (`*.testids.txt`) and a sample of hrefs (`*.hrefs.txt`). Look at
the screenshot to see what the UI is showing, grep the testids file for the
new selector name, then update the matching `xnuke/<category>.py` file.

The selectors that exist today, confirmed working as of 2026-06-09:

- Tweets: `article[data-testid="tweet"]`, caret `[data-testid="caret"]`, repost button `[data-testid="unretweet"]`
- Likes: `button[data-testid="unlike"]`
- Bookmarks: `button[data-testid="removeBookmark"]`
- DMs: row `[data-testid^="dm-conversation-item-"]`, panel `[data-testid="dm-conversation-panel"]`
- Confirm sheet: `[data-testid="confirmationSheetConfirm"]`

## License

No license declared. Don't redistribute without the author's permission;
do whatever you want with the code on your own X account.
