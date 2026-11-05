"""Shared helpers: logger, polite HTTP session, rate limiter, cleaning log."""
import csv
import functools
import logging
import time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CLEANING_LOG, FIGURES_DIR, REQUEST_TIMEOUT, USER_AGENT


def get_logger(name):
    """Return a logger that prints timestamped messages to the console."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _stop_on_block(response, *args, **kwargs):
    """Response hook: stop the whole run on HTTP 403 or 429."""
    if response.status_code in (403, 429):
        raise RuntimeError(
            f"HTTP {response.status_code} from {response.url}. The server refuses or throttles us; "
            "stopping the run (politeness rule). Do not retry right away."
        )


def polite_session():
    """Return a requests session with generic User-Agent, 30 s timeout and backoff retries on 5xx."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(500, 502, 503, 504), allowed_methods=("GET", "HEAD"))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.hooks["response"].append(_stop_on_block)
    session.request = functools.partial(session.request, timeout=REQUEST_TIMEOUT)
    return session


class RateLimiter:
    """Make sure at least `seconds` pass between two calls of wait()."""

    def __init__(self, seconds):
        self.seconds = seconds
        self._last = 0.0

    def wait(self):
        """Sleep until the minimum interval since the previous call has passed."""
        remaining = self.seconds - (time.monotonic() - self._last)
        if remaining > 0:
            time.sleep(remaining)
        self._last = time.monotonic()


def log_step(step, rows_before, rows_after, reason):
    """Write one cleaning/integration step to tables/cleaning_log.csv (a rerun replaces the same step)."""
    header = ["timestamp", "step", "rows_before", "rows_after", "rows_removed", "reason"]
    rows = []
    if CLEANING_LOG.exists():
        with open(CLEANING_LOG, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.reader(f)][1:]
    rows = [r for r in rows if r[1] != step]
    rows.append([datetime.now().isoformat(timespec="seconds"), step, rows_before, rows_after,
                 rows_before - rows_after, reason])
    CLEANING_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CLEANING_LOG, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_caption(figure_name, text):
    """Add or replace the caption of one figure in figures/captions.md."""
    path = FIGURES_DIR / "captions.md"
    sections = {}
    if path.exists():
        for block in path.read_text(encoding="utf-8").split("### ")[1:]:
            name, _, body = block.partition("\n")
            sections[name.strip()] = body.strip()
    sections[figure_name] = text.strip()
    path.write_text("# Figure captions\n\n" + "\n\n".join(f"### {n}\n{b}" for n, b in sorted(sections.items())) + "\n",
                    encoding="utf-8")
