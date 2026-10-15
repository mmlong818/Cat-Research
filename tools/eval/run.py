"""用当前代码跑一次固定问题的研究，打印工作空间与最终稿路径。

用法: python -m tools.eval.run Q2 [--depth deep] [--provider claude|openai|zhipu]
"""
import argparse
import json
import os
import time

from llm.profiles import PROFILES, default_profile
from orchestrator import ResearchOrchestrator
from tools.eval.questions import QUESTIONS


def final_draft_path(workspace: str) -> str:
    """会话选定的最终稿（评审过的版本）；盲评用它而不是带质量附录的 09_final.md。"""
    with open(os.path.join(workspace, "00_session.json"), encoding="utf-8") as f:
        meta = json.load(f)
    return os.path.join(workspace, "06_drafts", f"draft_{meta.get('final_draft', 0)}.md")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("label", choices=sorted(QUESTIONS))
    ap.add_argument("--depth", default="deep", choices=["quick", "standard", "deep"])
    ap.add_argument("--provider", choices=sorted(PROFILES), help="不传则用设置里的默认提供方")
    args = ap.parse_args(argv)

    profile = PROFILES[args.provider] if args.provider else default_profile()
    t0 = time.time()
    o = ResearchOrchestrator(profile=profile)
    o.run(QUESTIONS[args.label], depth=args.depth)
    result = {"label": args.label, "depth": args.depth, "provider": profile.provider,
              "workspace": o.workspace, "interrupted": o.interrupted,
              "minutes": round((time.time() - t0) / 60, 1)}
    if not o.interrupted:
        result["final_draft"] = final_draft_path(o.workspace)
    print("EVAL_RUN", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
