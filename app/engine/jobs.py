# SPDX-License-Identifier: Apache-2.0
"""Bounded background work: generation queue + scan concurrency gate.

Generation (300-dpi page renders / PDF embedding) runs on a small shared
executor so a burst of create requests queues instead of forking unbounded
threads. Scans (CPU-heavy OpenCV decode) run at most SCAN_SLOTS at a time;
callers that cannot get a slot quickly are told to retry rather than piling
onto the event loop.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

GEN_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gen")

SCAN_SLOTS = 2
_scan_sem = threading.BoundedSemaphore(SCAN_SLOTS)


def submit_generation(fn):
    GEN_POOL.submit(fn)


def run_scan_slot(fn, wait_s=1.0):
    """Run fn() while holding a scan slot. Returns (True, result) or
    (False, None) if no slot became free within wait_s."""
    if not _scan_sem.acquire(timeout=wait_s):
        return False, None
    try:
        return True, fn()
    finally:
        _scan_sem.release()
