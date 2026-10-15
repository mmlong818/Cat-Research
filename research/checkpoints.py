"""
阶段检查点：每个阶段完成后把 workspace 全量快照到 {workspace}/.checkpoints/NN_phase/，
连同阶段间上下文（计划、来源验证、事实核查、循环状态、研究轮次等）写入 state.json。
重放从某阶段开始时，先把 workspace 恢复到前一阶段的快照（草稿、评审、台账、查询登记一并回滚），
再删掉之后的检查点。workspace 通常 1MB 左右，全量快照比逐个追踪产物路径简单且不会漏文件。
"""
import hashlib
import json
import os
import shutil
from datetime import datetime

from tools.file_tools import WorkspaceDeleted, is_workspace_deleted

PHASES = ("clarify", "plan", "research", "sources", "ledger", "analyze", "draft", "improve", "finish")
CKPT_DIR = ".checkpoints"
_FILES = "files"
_STATE = "state.json"


def params_hash(params: dict, models: dict) -> str:
    blob = json.dumps({"params": params, "models": models}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class Checkpoints:
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.root = os.path.join(workspace, CKPT_DIR)

    def _dir(self, phase: str) -> str:
        return os.path.join(self.root, f"{PHASES.index(phase) + 1:02d}_{phase}")

    def save(self, phase: str, state: dict, params_hash: str):
        """先写到临时目录，完整后再改名，半截快照不会被当成检查点。"""
        final = self._dir(phase)
        tmp = f"{final}.tmp"
        if is_workspace_deleted(self.workspace):
            raise WorkspaceDeleted(self.workspace)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(self.workspace, os.path.join(tmp, _FILES), ignore=shutil.ignore_patterns(CKPT_DIR))
        record = {"phase": phase, "created_at": datetime.now().isoformat(),
                  "params_hash": params_hash, "state": state}
        with open(os.path.join(tmp, _STATE), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)

    def _record(self, phase: str) -> dict:
        with open(os.path.join(self._dir(phase), _STATE), encoding="utf-8") as f:
            return json.load(f)

    def list(self) -> list:
        """已完成阶段的检查点（从第一阶段起连续的前缀）。"""
        out = []
        for phase in PHASES:
            if not os.path.exists(os.path.join(self._dir(phase), _STATE)):
                break
            rec = self._record(phase)
            out.append({"phase": phase, "created_at": rec["created_at"], "params_hash": rec["params_hash"]})
        return out

    def resolve(self, from_phase=None) -> int:
        """校验重放起点，返回其在 PHASES 中的下标；None 表示从断点续跑。不合法时抛 ValueError。"""
        done = len(self.list())
        if from_phase is None:
            if done == 0:
                raise ValueError("该会话没有检查点，无法续跑")
            if done == len(PHASES):
                raise ValueError("研究已全部完成，请指定要重放的阶段")
            return done
        if from_phase not in PHASES:
            raise ValueError(f"未知阶段 {from_phase}，可选：{', '.join(PHASES[1:])}")
        start = PHASES.index(from_phase)
        if start == 0:
            raise ValueError("从澄清阶段重放等于重新研究，请直接新建研究")
        if start > done:
            raise ValueError(f"阶段 {PHASES[start - 1]} 尚无检查点，最多只能从 {PHASES[done]} 开始")
        return start

    def rollback(self, from_phase=None):
        """把 workspace 恢复到起点前一阶段的快照，删除之后的检查点；返回 (起点下标, 阶段上下文, 参数哈希)。"""
        start = self.resolve(from_phase)
        prev = PHASES[start - 1]
        for name in os.listdir(self.workspace):
            if name == CKPT_DIR:
                continue
            path = os.path.join(self.workspace, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        shutil.copytree(os.path.join(self._dir(prev), _FILES), self.workspace, dirs_exist_ok=True)
        for phase in PHASES[start:]:
            shutil.rmtree(self._dir(phase), ignore_errors=True)
        rec = self._record(prev)
        return start, rec["state"], rec["params_hash"]
