"""
研究任务持久化（SQLite）：任务状态与阶段记录，服务重启后仍可查询。
表结构参照 cat-research-v2 的 sessions/phases；报告正文仍在 workspace 目录，这里只存最终结果与状态。
运行期对象（事件队列、orchestrator 引用、暂停/停止事件）不入库，留在 api/app.py 内存里。
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

ACTIVE = ("pending", "running")
_COLUMNS = ("status", "question", "workspace", "session_id", "error", "result")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_tasks (
    task_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    workspace TEXT,
    session_id TEXT,
    error TEXT,
    result TEXT,
    state TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_phases (
    task_id TEXT NOT NULL,
    phase_num INTEGER NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    PRIMARY KEY (task_id, phase_num, started_at)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    session_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
"""


def _now() -> str:
    return datetime.now().isoformat()


class TaskStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()  # 串行化本进程内的读-改-写（merge 合并 state JSON）
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)  # 自动提交；reserve 显式开事务
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def reserve(self, task_id: str, question: str, limit: int, session_id=None, **state):
        """原子地检查并登记 pending 任务。成功返回 None；拒绝时返回原因：
        "limit"（达到并发上限）或 "busy"（该会话已有未结束的任务，重放不可并发）。"""
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                refusal = self._refusal(conn, limit, session_id)
                if refusal:
                    conn.execute("ROLLBACK")
                    return refusal
                now = _now()
                conn.execute(
                    "INSERT INTO research_tasks (task_id, question, status, session_id, state, created_at, updated_at)"
                    " VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                    (task_id, question, session_id, json.dumps(state, ensure_ascii=False), now, now),
                )
                conn.execute("COMMIT")
                return None
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    @classmethod
    def _refusal(cls, conn, limit: int, session_id):
        if session_id:
            marks = ",".join("?" * len(ACTIVE))
            busy = conn.execute(f"SELECT 1 FROM research_tasks WHERE session_id=? AND status IN ({marks})",
                                (session_id, *ACTIVE)).fetchone()
            if busy:
                return "busy"
        return "limit" if cls._count_active(conn) >= limit else None

    @staticmethod
    def _count_active(conn) -> int:
        marks = ",".join("?" * len(ACTIVE))
        return conn.execute(f"SELECT COUNT(*) FROM research_tasks WHERE status IN ({marks})", ACTIVE).fetchone()[0]

    def active_count(self) -> int:
        with self._conn() as conn:
            return self._count_active(conn)

    def merge(self, task_id: str, **fields):
        """更新列字段；其余字段合并进 state JSON。任务不存在时忽略。"""
        cols = {k: fields.pop(k) for k in _COLUMNS if k in fields}
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT state FROM research_tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                return
            state = {**json.loads(row["state"]), **fields}
            sets = "".join(f", {k}=?" for k in cols)
            conn.execute(
                f"UPDATE research_tasks SET state=?, updated_at=?{sets} WHERE task_id=?",
                (json.dumps(state, ensure_ascii=False), _now(), *cols.values(), task_id),
            )

    def get(self, task_id: str):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM research_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._to_dict(row) if row else None

    @staticmethod
    def _to_dict(row) -> dict:
        data = dict(row)
        state = json.loads(data.pop("state"))
        return {**state, **{k: v for k, v in data.items() if v is not None}}

    def list_tasks(self) -> list:
        """全部任务（新到旧），不含报告正文；phase_num/phase 取该任务最近一个阶段。"""
        sql = ("SELECT t.task_id, t.question, t.status, t.session_id, t.error, t.state, t.created_at,"
               " p.phase_num, p.phase FROM research_tasks t LEFT JOIN research_phases p ON p.rowid ="
               " (SELECT rowid FROM research_phases WHERE task_id=t.task_id"
               " ORDER BY started_at DESC, rowid DESC LIMIT 1)"
               " ORDER BY t.created_at DESC, t.rowid DESC")
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute(sql)]
        for row in rows:
            state = json.loads(row.pop("state"))
            for key in ("depth", "language", "provider", "core_model", "support_model"):
                row[key] = state.get(key)
        return rows

    def session_tasks(self, session_id=None, task_id=None) -> list:
        """某会话（含其上的重放任务）或单个任务的概况与阶段记录，旧到新。"""
        col, value = ("session_id", session_id) if session_id else ("task_id", task_id)
        with self._conn() as conn:
            rows = conn.execute(f"SELECT task_id, status, error, state, created_at FROM research_tasks"
                                f" WHERE {col}=? ORDER BY created_at, rowid", (value,)).fetchall()
        return [{"task_id": r["task_id"], "status": r["status"], "error": r["error"], "created_at": r["created_at"],
                 "replay_from": json.loads(r["state"]).get("replay_from"), "phases": self.phases(r["task_id"])}
                for r in rows]

    def active_ids(self) -> list:
        marks = ",".join("?" * len(ACTIVE))
        with self._conn() as conn:
            rows = conn.execute(f"SELECT task_id FROM research_tasks WHERE status IN ({marks})", ACTIVE)
            return [r["task_id"] for r in rows]

    def mark_interrupted(self) -> int:
        """服务启动时调用：上次进程里未结束的任务线程已不存在，标记为 interrupted。"""
        marks = ",".join("?" * len(ACTIVE))
        with self._lock, self._conn() as conn:
            now = _now()
            conn.execute(
                f"UPDATE research_phases SET status='interrupted', finished_at=? WHERE finished_at IS NULL"
                f" AND task_id IN (SELECT task_id FROM research_tasks WHERE status IN ({marks}))",
                (now, *ACTIVE),
            )
            cur = conn.execute(
                f"UPDATE research_tasks SET status='interrupted', updated_at=? WHERE status IN ({marks})",
                (now, *ACTIVE),
            )
            return cur.rowcount

    def delete(self, task_id: str):
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM research_phases WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM research_tasks WHERE task_id=?", (task_id,))

    def start_phase(self, task_id: str, phase_num: int, phase: str):
        """开始新阶段：上一个未结束的阶段视为完成。任务已被删除时忽略（后台线程可能晚于删除接口才报告阶段）。"""
        with self._lock, self._conn() as conn:
            if conn.execute("SELECT 1 FROM research_tasks WHERE task_id=?", (task_id,)).fetchone() is None:
                return
            now = _now()
            conn.execute(
                "UPDATE research_phases SET status='completed', finished_at=? WHERE task_id=? AND finished_at IS NULL",
                (now, task_id),
            )
            conn.execute(
                "INSERT INTO research_phases (task_id, phase_num, phase, status, started_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (task_id, phase_num, phase, now),
            )

    def finish_phase(self, task_id: str, status: str, error=None):
        """任务结束时收尾当前阶段。"""
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE research_phases SET status=?, finished_at=?, error=? WHERE task_id=? AND finished_at IS NULL",
                (status, _now(), error, task_id),
            )

    # ── 审计日志：只追加；不随任务删除或重放回滚而清除 ──

    def audit(self, task_id: str, kind: str, payload: dict | None = None):
        """追加一条审计记录；任务不存在时忽略（避免对任意 ID 的请求写入垃圾记录）。"""
        with self._conn() as conn:
            row = conn.execute("SELECT session_id FROM research_tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                return
            conn.execute(
                "INSERT INTO audit_log (task_id, session_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, row["session_id"], kind, json.dumps(payload or {}, ensure_ascii=False), _now()),
            )

    def attach_session(self, task_id: str, session_id: str, workspace: str):
        """任务的工作空间建好后记下会话 ID，并回填此前尚无会话 ID 的审计记录。"""
        self.merge(task_id, session_id=session_id, workspace=workspace)
        with self._conn() as conn:
            conn.execute("UPDATE audit_log SET session_id=? WHERE task_id=? AND session_id IS NULL",
                         (session_id, task_id))

    def audit_log(self, session_id=None, task_id=None) -> list:
        col, value = ("session_id", session_id) if session_id else ("task_id", task_id)
        with self._conn() as conn:
            rows = conn.execute(f"SELECT task_id, session_id, kind, payload, created_at FROM audit_log"
                                f" WHERE {col}=? ORDER BY id", (value,))
            return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def phases(self, task_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT phase_num, phase, status, started_at, finished_at, error FROM research_phases"
                " WHERE task_id=? ORDER BY started_at, rowid",
                (task_id,),
            )
            return [dict(r) for r in rows]
