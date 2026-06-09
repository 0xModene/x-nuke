# x-nuke

Wipe your own X/Twitter account by driving a Chromium-based browser over CDP.

Deletes: tweets, replies, reposts, likes, bookmarks, DMs (1:1 + groups), owned lists.

Does not touch: follows, followers, blocks, mutes.

**Destructive and irreversible.**

## Prerequisites

- macOS or Linux
- Python 3.10+
- One of: Brave, Chrome, Edge, Chromium, Arc (macOS), Vivaldi

## Install and run

```bash
git clone https://github.com/0xModene/x-nuke.git
cd x-nuke
./nuke.sh
```

`./nuke.sh` runs 7 categories in parallel, one tab each. Each tab closes itself when its category is empty. Output is prefixed `[tweets-posts]`, `[likes]`, etc.

If you aren't signed in to x.com, a login tab opens and the run waits up to 10 minutes for you to finish.

## Single-category runs

```bash
./nuke.sh tweets           # posts + replies + search, sequential, one tab
./nuke.sh tweets-posts
./nuke.sh tweets-replies
./nuke.sh tweets-search    # final sweep for chain-buried replies
./nuke.sh likes
./nuke.sh bookmarks
./nuke.sh dms
./nuke.sh lists
```

## Environment variables

```bash
BROWSER=brave|chrome|edge|chromium|arc|vivaldi   # default: auto-detect
CDP_PORT=9222                                    # default: 9222
```

## Direct Python usage

```bash
python wipe.py --help
python wipe.py status                            # verify login
python wipe.py <category> --yes-really-delete --force --cdp http://127.0.0.1:9222
python wipe.py <category> --yes-really-delete --force --browser chrome
```

## Logs

`logs/<UTC-timestamp>.log` per run. `logs/diag-<category>-stuck-*.png|html|testids.txt` written if a category gets stuck (selectors changed).
