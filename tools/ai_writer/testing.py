"""通信を模擬するテスト用の部品（Provider・Core Writer・探索機能のテストで共有する）。

本番の経路からは使わない。``FakeTransport`` は ``transport.Transport`` と同じ口を持ち、
台本（SSE の行、``FakeHandle``、または投げる例外）を順に返す。
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

_END = object()


def sse(*texts: str, finish: str | None = "stop", done: bool = True) -> list[bytes]:
    """OpenAI 互換 SSE の行を作る。各片は文字数ぶんの token_ids を持つ（終端トークンは数えない）。"""
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': t}, 'token_ids': [1] * len(t)}]}, ensure_ascii=False)}\n".encode()
             for t in texts]
    if finish:
        lines.append(f"data: {json.dumps({'choices': [{'delta': {'content': ''}, 'finish_reason': finish, 'token_ids': [9]}]})}\n".encode())
    if done:
        lines.append(b"data: [DONE]\n")
    return lines


class FakeHandle:
    """行を順に返す。``hold=True`` なら行を出し切ったあと close されるまで待つ（遅い応答の模擬）。"""

    def __init__(self, lines: list[bytes], *, hold: bool = False, fail_after: int | None = None) -> None:
        self._q: queue.Queue[object] = queue.Queue()
        for line in lines:
            self._q.put(line)
        if not hold:
            self._q.put(_END)
        self.closed = threading.Event()
        self._fail_after = fail_after
        self.on_close: Callable[[], None] | None = None

    def __iter__(self) -> Iterator[bytes]:
        n = 0
        while True:
            item = self._q.get(timeout=5)
            if item is _END or self.closed.is_set():
                return
            if self._fail_after is not None and n >= self._fail_after:
                raise OSError("connection reset")
            n += 1
            assert isinstance(item, bytes)
            yield item

    def close(self) -> None:
        if not self.closed.is_set():
            self.closed.set()
            if self.on_close:
                self.on_close()
        self._q.put(_END)


class FakeTransport:
    """台本を順に返す模擬の通信。送った要求（``calls``）と、同時に開いていた本数の最大（``max_active``）を記録する。"""

    def __init__(self, *scripts: object) -> None:
        self.scripts = list(scripts)
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def open_stream(self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> FakeHandle:
        self.calls.append({"url": url, "headers": headers, "body": body})
        item = self.scripts.pop(0)
        if isinstance(item, BaseException):
            raise item
        handle = item if isinstance(item, FakeHandle) else FakeHandle(item)  # type: ignore[arg-type]
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        handle.on_close = self._closed
        return handle

    def _closed(self) -> None:
        with self._lock:
            self.active -= 1
