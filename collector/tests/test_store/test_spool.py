"""The on-disk queue."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from ecowitt.collector.spool import Spool


def make(tmp_path: Path, max_bytes: int = 1_000_000, **kw: object) -> Spool:
    return Spool(tmp_path / "spool", max_bytes, **kw)  # type: ignore[arg-type]


def drain(spool: Spool) -> list[str]:
    out = []
    while (path := spool.oldest()) is not None:
        out.append(spool.read(path))
        spool.ack(path)
    return out


def test_reports_come_back_in_arrival_order(tmp_path: Path) -> None:
    spool = make(tmp_path)
    for i in range(50):
        spool.enqueue(f"r{i}")

    assert drain(spool) == [f"r{i}" for i in range(50)]
    assert len(spool) == 0
    assert spool.stats().bytes == 0


def test_a_restart_finds_what_was_waiting_in_the_same_order(tmp_path: Path) -> None:
    """A new process over the same directory picks up the backlog."""
    first = make(tmp_path)
    for i in range(5):
        first.enqueue(f"r{i}")
    first.ack(first.oldest())  # type: ignore[arg-type]

    second = make(tmp_path)

    assert len(second) == 4
    assert second.stats().bytes == sum(len(f"r{i}") for i in range(1, 5))
    assert drain(second) == ["r1", "r2", "r3", "r4"]


def test_a_crash_mid_write_leaves_nothing_half_written(tmp_path: Path) -> None:
    """A temporary file from an interrupted write is removed, never replayed."""
    spool = make(tmp_path)
    spool.enqueue("complete")
    (spool.pending_dir / ".00000000000000000099-0000000000.lp.tmp").write_text("trunc")

    reopened = make(tmp_path)

    assert drain(reopened) == ["complete"]
    assert list(reopened.pending_dir.iterdir()) == []


def test_over_the_size_limit_the_oldest_are_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The newest readings are the ones worth keeping, and the disk must not fill."""
    spool = make(tmp_path, max_bytes=30)
    with caplog.at_level(logging.WARNING):
        for i in range(10):
            spool.enqueue(f"report-{i}")  # 8 bytes each

    assert spool.stats().bytes <= 30
    assert drain(spool) == ["report-7", "report-8", "report-9"]
    assert spool.dropped == 7
    assert "dropped the oldest report" in caplog.text


def test_a_single_report_larger_than_the_limit_is_still_kept(tmp_path: Path) -> None:
    """The newest report is never dropped, or nothing could ever be spooled."""
    spool = make(tmp_path, max_bytes=5)
    spool.enqueue("a much longer report than five bytes")

    assert len(spool) == 1


def test_quarantine_moves_a_report_out_of_the_queue(tmp_path: Path) -> None:
    spool = make(tmp_path)
    spool.enqueue("bad")
    spool.enqueue("good")
    bad = spool.oldest()
    assert bad is not None

    spool.quarantine(bad)

    assert drain(spool) == ["good"]
    assert [p.read_text() for p in spool.rejected_dir.iterdir()] == ["bad"]
    assert spool.rejected_count() == 1


def test_quarantine_body_keeps_a_report_without_queueing_it(tmp_path: Path) -> None:
    spool = make(tmp_path)

    spool.quarantine_body("refused")

    assert len(spool) == 0
    assert spool.rejected_count() == 1


def test_rejected_reports_are_bounded_oldest_first(tmp_path: Path) -> None:
    spool = make(tmp_path, max_rejected=3)
    for i in range(6):
        spool.quarantine_body(f"r{i}")

    kept = sorted(spool.rejected_dir.iterdir())
    assert [p.read_text() for p in kept] == ["r3", "r4", "r5"]


def test_stats_report_the_oldest_age(tmp_path: Path) -> None:
    now = [1_000_000.0]
    spool = make(tmp_path, clock=lambda: now[0])
    assert spool.stats().oldest_seconds is None

    spool.enqueue("x")
    path = spool.oldest()
    assert path is not None
    os.utime(path, (now[0] - 90, now[0] - 90))

    assert spool.stats().oldest_seconds == pytest.approx(90)
    assert spool.stats().files == 1


def test_a_failure_to_store_is_reported_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A full or read-only disk loses the report, and says so."""
    spool = make(tmp_path)
    spool.pending_dir.chmod(0o500)
    try:
        assert spool.enqueue("lost") is False
    finally:
        spool.pending_dir.chmod(0o700)

    assert len(spool) == 0
    assert "it is lost" in caplog.text


def test_ack_of_an_unknown_path_is_harmless(tmp_path: Path) -> None:
    spool = make(tmp_path)
    spool.enqueue("kept")

    spool.ack(spool.pending_dir / "not-queued.lp")

    assert len(spool) == 1


def test_files_that_vanish_count_as_empty(tmp_path: Path) -> None:
    """Someone clearing the directory by hand must not break the size accounting."""
    spool = make(tmp_path)
    spool.enqueue("x")
    path = spool.oldest()
    assert path is not None
    path.unlink()

    assert spool.stats().oldest_seconds is None
    spool.ack(path)
    assert spool.stats().bytes == 0


def test_a_rejected_report_that_cannot_be_moved_is_deleted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    spool = make(tmp_path)
    spool.enqueue("bad")
    path = spool.oldest()
    assert path is not None
    spool.rejected_dir.chmod(0o500)
    try:
        spool.quarantine(path)
    finally:
        spool.rejected_dir.chmod(0o700)

    assert not path.exists()
    assert len(spool) == 0
    assert "could not keep rejected report" in caplog.text


def test_a_rejected_body_that_cannot_be_kept_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    spool = make(tmp_path)
    spool.rejected_dir.chmod(0o500)
    try:
        spool.quarantine_body("refused")
    finally:
        spool.rejected_dir.chmod(0o700)

    assert "could not keep a rejected report" in caplog.text


def test_the_size_of_a_vanished_file_is_zero(tmp_path: Path) -> None:
    """A file deleted between listing and measuring must not raise."""
    from ecowitt.collector.spool import _size

    assert _size(tmp_path / "gone.lp") == 0


def test_a_report_is_synced_to_disk_before_it_counts_as_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file and the directory entry for it are both flushed.

    Without the first, a power cut can leave an empty file; without the second, the rename
    that gives it its name can be lost. Either way the report would be gone.
    """
    import ecowitt.collector.spool as spool_module

    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(spool_module.os, "fsync", lambda fd: synced.append(fd) or real(fd))

    make(tmp_path).enqueue("durable")

    assert len(synced) == 2
