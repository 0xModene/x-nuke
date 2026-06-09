import sys
import time
from pathlib import Path
from datetime import datetime, timezone

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
_log_path = LOG_DIR / f"{_run_id}.log"
_fh = open(_log_path, "a", buffering=1, encoding="utf-8")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str, *, level: str = "info") -> None:
    line = f"[{_ts()}] {level.upper():5} {msg}"
    print(line, file=sys.stderr, flush=True)
    _fh.write(line + "\n")


def info(msg: str) -> None:
    log(msg, level="info")


def warn(msg: str) -> None:
    log(msg, level="warn")


def err(msg: str) -> None:
    log(msg, level="error")


def progress(category: str, n: int, last: str = "") -> None:
    suffix = f" — last: {last}" if last else ""
    info(f"{category}: deleted {n}{suffix}")


def log_path() -> Path:
    return _log_path
