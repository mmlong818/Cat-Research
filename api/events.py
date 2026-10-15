"""
研究进度事件广播：每个任务一个 EventBroadcaster，多个 SSE 订阅者各有独立队列。
事件来自后台研究线程，publish 线程安全且不阻塞；SSE 侧沿用 queue.Queue + 轮询的方式取事件。
最近 BUFFER_SIZE 条事件留作回放缓冲，刷新页面、多开标签页或断线重连的订阅者先回放再接实时事件。
"""
import threading
import time
from collections import deque
from datetime import datetime
from queue import Queue

BUFFER_SIZE = 500
FINISHED_TTL = 3600  # 任务结束后广播器保留多久（秒），供迟到的订阅者回放
NOT_REPLAYED = ("heartbeat",)  # 只对在线订阅者有意义；快照里已带 elapsed 等状态


class EventBroadcaster:
    def __init__(self, max_buffer: int = BUFFER_SIZE):
        self._lock = threading.Lock()
        self._buffer: deque[dict] = deque(maxlen=max_buffer)
        self._subs: list[Queue] = []
        self.closed = False
        self.finished_at: float | None = None

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, event: dict) -> None:
        with self._lock:
            if event.get("type") not in NOT_REPLAYED:
                self._buffer.append(event)
            if event.get("type") == "end" and not self.closed:
                self.closed = True
                self.finished_at = time.monotonic()
            for q in self._subs:
                q.put_nowait(event)

    def subscribe(self) -> tuple[list[dict], Queue]:
        """原子地取回放缓冲并登记队列：回放与实时事件之间既不丢也不重复"""
        q: Queue = Queue()
        with self._lock:
            replay = list(self._buffer)
            self._subs.append(q)
        return replay, q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def close(self) -> None:
        """补发结束标记，让仍在订阅的客户端收尾；已结束则无操作"""
        if not self.closed:
            self.publish({"type": "end", "data": {}, "timestamp": datetime.now().isoformat()})


class BroadcastRegistry:
    """task_id → 广播器；已结束超过 ttl 的在创建新广播器时清理"""

    def __init__(self, ttl: float = FINISHED_TTL):
        self._lock = threading.Lock()
        self._items: dict[str, EventBroadcaster] = {}
        self._ttl = ttl

    def create(self, task_id: str) -> EventBroadcaster:
        bc = EventBroadcaster()
        with self._lock:
            now = time.monotonic()
            expired = [k for k, v in self._items.items()
                       if v.finished_at is not None and now - v.finished_at > self._ttl]
            for k in expired:
                del self._items[k]
            self._items[task_id] = bc
        return bc

    def get(self, task_id: str) -> EventBroadcaster | None:
        with self._lock:
            return self._items.get(task_id)

    def drop(self, task_id: str) -> EventBroadcaster | None:
        with self._lock:
            return self._items.pop(task_id, None)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for v in self._items.values() if not v.closed)
