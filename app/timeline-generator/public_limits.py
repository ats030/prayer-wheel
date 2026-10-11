"""Bounded process-local HTTP budgets, separate from the durable trial AI quota."""
import math
import threading
import time


class BudgetExceeded(Exception):
    def __init__(self, code, retry_after):
        self.code, self.retry_after = code, retry_after


class PublicLimits:
    def __init__(self, *, requests=300, starts=30, reads=120, writes=30,
                 owner_bytes=4 * 1024 * 1024, total_bytes=32 * 1024 * 1024,
                 owners=1000, window=60, clock=time.monotonic):
        values = (requests, starts, reads, writes, owner_bytes, total_bytes, owners, window)
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Positive HTTP limits required")
        self.requests, self.starts, self.reads, self.writes = requests, starts, reads, writes
        self.owner_bytes, self.total_bytes, self.owners = owner_bytes, total_bytes, owners
        self.window, self.clock, self.lock = window, clock, threading.Lock()
        self.bucket = None
        self.counts, self.people = {}, {}

    def current(self):
        moment = self.clock()
        bucket = int(moment // self.window)
        if bucket != self.bucket:
            self.bucket, self.counts, self.people = bucket, {}, {}
        return max(1, math.ceil((bucket + 1) * self.window - moment))

    def check_request(self, *, start=False):
        with self.lock:
            retry = self.current()
            name, limit = ("starts", self.starts) if start else ("requests", self.requests)
            if self.counts.get(name, 0) >= limit:
                raise BudgetExceeded("request_rate", retry)
            self.counts[name] = self.counts.get(name, 0) + 1

    def person(self, owner, retry):
        if owner not in self.people:
            if len(self.people) >= self.owners:
                raise BudgetExceeded("request_rate", retry)
            self.people[owner] = {"reads": 0, "writes": 0, "bytes": 0}
        return self.people[owner]

    def check_owner(self, owner, *, write=False):
        with self.lock:
            retry = self.current()
            person = self.person(owner, retry)
            name, limit = ("writes", self.writes) if write else ("reads", self.reads)
            if person[name] >= limit:
                raise BudgetExceeded("request_rate", retry)
            person[name] += 1

    def check_response(self, owner, length):
        with self.lock:
            retry = self.current()
            person = self.person(owner, retry)
            if person["bytes"] + length > self.owner_bytes or self.counts.get("bytes", 0) + length > self.total_bytes:
                raise BudgetExceeded("response_budget", retry)
            person["bytes"] += length
            self.counts["bytes"] = self.counts.get("bytes", 0) + length
