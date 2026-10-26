"""HTTP の送受信だけを受け持つ層。テストではこれを模擬に差し替える。

``Transport.open_stream`` は SSE の応答を開き、行を順に返す ``StreamHandle`` を返す。
``close()`` は別スレッドから呼んでもよく、読み取り中の接続を閉じる（キャンセルに使う）。
HTTP の誤りは ``TransportError``（status と本文の一部）として投げる。トークンは扱わない。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any, Protocol


class TransportError(RuntimeError):
    def __init__(self, status: int | None, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body
        self.attempts = 1  # 429 で送り直したときは Provider が回数を入れる


class StreamHandle(Protocol):
    def __iter__(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...


class Transport(Protocol):
    def open_stream(self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> StreamHandle: ...


class _UrllibStream:
    def __init__(self, resp: Any) -> None:
        self._resp = resp

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._resp)

    def close(self) -> None:
        try:
            self._resp.close()
        except Exception:  # noqa: BLE001 - 閉じる途中の誤りはキャンセルの妨げにしない
            pass


class UrllibTransport:
    """標準ライブラリだけで送る既定の実装。"""

    def open_stream(self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> StreamHandle:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        for key, value in headers.items():
            req.add_header(key, value)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                text = e.read().decode("utf-8", errors="replace")[:2000]
            except Exception:  # noqa: BLE001
                text = ""
            raise TransportError(e.code, text) from e
        except urllib.error.URLError as e:
            raise TransportError(None, f"URLError: {e.reason}") from e
        except TimeoutError as e:
            # 接続・応答ヘッダ待ちのタイムアウト。自動では再送せず、生成エラーとして記録させる
            raise TransportError(None, f"timeout: {e}") from e
        return _UrllibStream(resp)
