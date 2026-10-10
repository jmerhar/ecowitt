"""Reports waiting for InfluxDB, kept on disk so an outage or a restart loses none of them.

A console has no backlog: whatever it sends while the database is unreachable is gone unless
something keeps it. Each report's encoded rows become one file, written atomically and named
so that lexical order is arrival order; the delivery loop replays them oldest first.

Replaying a report InfluxDB had in fact already stored -- a crash between its acceptance and
the file's removal -- is harmless: a point with the same series and timestamp overwrites
itself.

Bounded by total size. Beyond the limit the oldest reports are dropped, because a full disk
would stop every container on the host, and the newest readings are the ones worth having.
Reports InfluxDB refused outright are kept apart in `rejected/` for inspection, bounded by
count.

The pending list is held in memory after one directory listing at startup, so that draining a
long backlog does not re-list the directory for every report. That is sound only because this
process is the directory's sole writer.
"""

from __future__ import annotations

import itertools
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SUFFIX = ".json"
#: Line protocol an older version spooled. Still listed, so such files reach delivery, which
#: cannot read them as rows and sets them aside rather than leaving them unseen.
LEGACY_SUFFIX = ".lp"
#: Reports refused by InfluxDB that are kept for inspection; older ones are deleted.
MAX_REJECTED = 1000


@dataclass(frozen=True)
class SpoolStats:
    """How much is waiting."""

    files: int
    bytes: int
    #: Age of the oldest waiting report, from its file's modification time; None when empty.
    oldest_seconds: float | None


class Spool:
    """A bounded, durable queue of encoded reports."""

    def __init__(
        self,
        directory: Path,
        max_bytes: int,
        *,
        max_rejected: int = MAX_REJECTED,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.pending_dir = directory / "pending"
        self.rejected_dir = directory / "rejected"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.rejected_dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._max_rejected = max_rejected
        self._clock = clock
        self._sequence = itertools.count()
        self.dropped = 0

        # A temporary file left by a crash mid-write is incomplete by definition.
        for leftover in self.pending_dir.glob(".*.tmp"):
            leftover.unlink(missing_ok=True)
        self._pending: deque[Path] = deque(_listed(self.pending_dir))
        # Sizes are remembered rather than re-read on removal: a file deleted from outside
        # can no longer be measured, and subtracting zero would leave the total too high for
        # good -- eventually dropping new reports the spool had room for.
        self._sizes = {p: _size(p) for p in self._pending}
        self._bytes = sum(self._sizes.values())
        if self._pending:
            logger.info("%d report(s) waiting from before the restart", len(self._pending))

    def __len__(self) -> int:
        return len(self._pending)

    def enqueue(self, body: str) -> bool:
        """Store a report to be written later, returning whether it was stored.

        A failure to store -- a full or read-only disk -- loses the report, and is logged as
        the data loss it is; there is nowhere left to keep it.
        """
        try:
            path = _write_atomically(self.pending_dir, self._name(), body)
        except OSError:
            logger.exception("could not spool a report; it is lost")
            return False
        self._pending.append(path)
        self._sizes[path] = _size(path)
        self._bytes += self._sizes[path]
        self._enforce_limit()
        return True

    def oldest(self) -> Path | None:
        """The next report to replay, or None if nothing is waiting."""
        return self._pending[0] if self._pending else None

    def read(self, path: Path) -> str:
        """The encoded rows in a spooled report."""
        return path.read_text(encoding="utf-8")

    def ack(self, path: Path) -> None:
        """Forget a report InfluxDB has accepted."""
        self._forget(path)
        path.unlink(missing_ok=True)

    def quarantine(self, path: Path) -> None:
        """Move a report InfluxDB refused, or that cannot be read, out of the queue."""
        self._forget(path)
        try:
            path.replace(self.rejected_dir / path.name)
        except OSError:
            logger.exception("could not keep rejected report %s; deleting it", path.name)
            path.unlink(missing_ok=True)
        self._trim_rejected()

    def quarantine_body(self, body: str) -> None:
        """Keep a report InfluxDB refused on its first attempt, without queueing it."""
        try:
            _write_atomically(self.rejected_dir, self._name(), body)
        except OSError:
            logger.exception("could not keep a rejected report")
        self._trim_rejected()

    def stats(self) -> SpoolStats:
        """How many reports are waiting, their total size, and the oldest one's age."""
        oldest = None
        if self._pending:
            try:
                oldest = max(0.0, self._clock() - self._pending[0].stat().st_mtime)
            except OSError:
                oldest = None
        return SpoolStats(len(self._pending), self._bytes, oldest)

    def rejected_count(self) -> int:
        """How many refused reports are kept for inspection."""
        return len(_listed(self.rejected_dir))

    def _name(self) -> str:
        """A file name that sorts after every earlier one from this process.

        The sequence number breaks ties within one nanosecond tick, and on a clock that does
        not advance between two calls.
        """
        return f"{time.time_ns():020d}-{next(self._sequence):010d}{SUFFIX}"

    def _forget(self, path: Path) -> None:
        """Drop a report from the in-memory queue and the size total."""
        try:
            self._pending.remove(path)
        except ValueError:
            return
        self._bytes -= self._sizes.pop(path, 0)

    def _enforce_limit(self) -> None:
        """Drop the oldest reports until the queue fits, always keeping the newest."""
        while self._bytes > self._max_bytes and len(self._pending) > 1:
            victim = self._pending.popleft()
            self._bytes -= self._sizes.pop(victim, 0)
            victim.unlink(missing_ok=True)
            self.dropped += 1
            logger.warning("spool over %d bytes: dropped the oldest report", self._max_bytes)

    def _trim_rejected(self) -> None:
        """Delete the oldest rejected reports beyond the cap."""
        kept = _listed(self.rejected_dir)
        for path in kept[: max(0, len(kept) - self._max_rejected)]:
            path.unlink(missing_ok=True)


def _listed(directory: Path) -> list[Path]:
    """The spool files in a directory, oldest first.

    Names begin with the time they were written, so sorting by name sorts by age whatever
    the suffix.
    """
    files = [*directory.glob("*" + SUFFIX), *directory.glob("*" + LEGACY_SUFFIX)]
    return sorted(files, key=lambda path: path.name)


def _write_atomically(directory: Path, name: str, body: str) -> Path:
    """Write a file so that it either exists complete or not at all.

    Written under a dot-prefixed temporary name, flushed to disk, then renamed into place; the
    directory is synced too, or the rename itself could be lost to a power cut.
    """
    final = directory / name
    temporary = directory / f".{name}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, final)
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return final


def _size(path: Path) -> int:
    """A file's size, or zero if it has gone."""
    try:
        return path.stat().st_size
    except OSError:
        return 0
