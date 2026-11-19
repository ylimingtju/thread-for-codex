"""Read local Codex turn metadata and token counters for registered chats."""
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from hashlib import blake2s
import json
import os
import re
from threading import Lock


FIELDS = ("input_tokens", "output_tokens", "total_tokens")
ZERO = (0, 0, 0)
EVENT = re.compile(rb'"type"\s*:\s*"(?:task_started|token_count)"')
LOCK = Lock()


def _usage(data):
    if not isinstance(data, dict):
        return None
    inp, out = data.get("input_tokens"), data.get("output_tokens")
    if not all(type(value) is int and value >= 0 for value in (inp, out)):
        return None
    total = data.get("total_tokens", inp + out)
    if type(total) is int and total >= 0:
        return inp, out, total
    return None


def _add(models, model, counts):
    row = models.setdefault(model, [0, 0, 0])
    for index, count in enumerate(counts):
        row[index] += count


def _timestamp(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return None


@dataclass
class _Counts:
    models: dict = field(default_factory=dict)
    partial: bool = False
    turn_id: str = None
    start: float = None
    awaiting_context: bool = False
    model: str = "unknown"
    cumulative: tuple = None
    last_only_event: tuple = None

    def in_scope(self, cutoff):
        return cutoff is None or (self.start is not None and self.start >= cutoff)

    def tokens(self, info, timestamp, cutoff):
        current = _usage(info.get("total_token_usage"))
        last = _usage(info.get("last_token_usage"))
        in_scope = self.in_scope(cutoff)
        uncertain = in_scope or self.start is None
        if ((current is None and info.get("total_token_usage") is not None)
                or (last is None and info.get("last_token_usage") is not None)):
            self.partial |= uncertain
        previous = self.cumulative
        if current is None:
            # Older log formats may only report the last request.
            if last is None:
                self.partial |= uncertain
                return
            event = (self.turn_id, timestamp, last)
            if event == self.last_only_event:
                return
            self.last_only_event = event
            delta = last
            self.cumulative = tuple(a + b for a, b in zip(previous or ZERO, last))
        else:
            self.last_only_event = None
            self.cumulative = current
            delta = tuple(a - b for a, b in zip(current, previous or ZERO))
            if any(value < 0 for value in delta):
                # The runtime reset its cumulative counters.
                delta = last or current
            elif previous is None and last is not None and last != current:
                # The first surviving snapshot can include an earlier, unlabelled prefix.
                prefix = tuple(a - b for a, b in zip(current, last))
                if all(value >= 0 for value in prefix):
                    if cutoff is None:
                        _add(self.models, "unknown", prefix)
                    self.partial |= uncertain
                    delta = last
        confirmed_zero = self.model != "unknown" and current in (ZERO, None) and last in (ZERO, None)
        if in_scope and (any(delta) or confirmed_zero):
            _add(self.models, self.model, delta)
            self.partial |= self.model == "unknown"
        elif any(delta) and self.start is None:
            self.partial = True

    def consume(self, line, cutoff):
        # The native envelope puts its record type before payload. Skip message bodies
        # (including attachments and tool results) without deserializing them.
        payload_at = line.find(b'"payload"', 0, 512)
        header = line[:payload_at] if payload_at >= 0 else line[:512]
        if b'"turn_context"' not in header and not (
            b'"event_msg"' in header and EVENT.search(line, max(0, payload_at), len(header) + 512)
        ):
            return
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError):
            self.partial = True
            return
        if not isinstance(record, dict):
            self.partial = True
            return
        data = record.get("payload")
        if not isinstance(data, dict):
            return
        context = record.get("type") == "turn_context"
        kind = data.get("type")
        timestamp = record.get("timestamp")
        if context or kind == "task_started":
            turn_id = data.get("turn_id")
            same_turn = turn_id is not None and turn_id == self.turn_id
            if self.awaiting_context and (turn_id is None or self.turn_id is None):
                same_turn = True
            if kind == "task_started" or self.start is None or not same_turn:
                self.start = _timestamp(timestamp)
                self.turn_id = turn_id
                self.model = "unknown"
            self.awaiting_context = not context
            if context:
                self.turn_id = turn_id or self.turn_id
                model = data.get("model")
                self.model = model.strip() if isinstance(model, str) and model.strip() else "unknown"
        elif kind == "token_count" and isinstance(data.get("info"), dict):
            self.tokens(data["info"], timestamp, cutoff)


def _signature(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _boundary(stream, offset):
    # Detect a truncation followed by a fast regrowth between polls.
    start = max(0, offset - 128)
    stream.seek(start)
    return blake2s(stream.read(offset - start), digest_size=16).digest()


@dataclass
class _Rollout:
    signature: tuple = None
    offset: int = 0
    boundary: bytes = None
    counts: _Counts = field(default_factory=_Counts)

    def read(self, path, cutoff):
        if self.signature == _signature(os.stat(path)):
            return self.counts
        with open(path, "rb") as stream:
            signature = _signature(os.fstat(stream.fileno()))
            size = signature[2]
            if (self.signature is None or signature[:2] != self.signature[:2]
                    or size <= self.signature[2] or self.boundary != _boundary(stream, self.offset)):
                self.offset = 0
                self.counts = _Counts()
            stream.seek(self.offset)
            while self.offset < size:
                line = stream.readline(size - self.offset)
                if not line.endswith(b"\n"):
                    break
                self.counts.consume(line, cutoff)
                self.offset += len(line)
            self.boundary = _boundary(stream, self.offset)
            self.signature = signature
        return self.counts


@lru_cache(maxsize=256)
def _reader(path, cutoff):
    return _Rollout()


def usage_for_threads(sources):
    """Combine each rollout once, from its earliest included turn start (Unix seconds)."""
    paths = {}
    partial = False
    for path, cutoff in sources:
        if not path:
            partial = True
        elif path not in paths or cutoff is None or (paths[path] is not None and cutoff < paths[path]):
            paths[path] = cutoff

    models = {}
    with LOCK:
        for path, cutoff in paths.items():
            reader = _reader(path, cutoff)
            try:
                counts = reader.read(path, cutoff)
            except OSError:
                reader.signature = None
                partial = True
                continue
            for model, counts_for_model in counts.models.items():
                _add(models, model, counts_for_model)
            partial |= counts.partial
    rows = sorted(models.items(), key=lambda row: (-row[1][2], row[0]))
    totals = [sum(values[i] for values in models.values()) for i in range(3)]
    return {**dict(zip(FIELDS, totals)), "partial": partial,
            "models": [{"model": model, **dict(zip(FIELDS, values))} for model, values in rows]}
