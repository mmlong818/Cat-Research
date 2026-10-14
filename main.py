"""
多智能体研究系统 - 主入口
Multi-Agent Research System

使用方法：
  python main.py                    # 交互模式
  python main.py "你的研究问题"     # 直接提问模式
"""
import os
import sys
import time

# Windows GBK 控制台 emoji 兼容（reconfigure 原地修改；重新包装 buffer 会在旧包装被回收时关闭它）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# 检查 Python 版本
if sys.version_info < (3, 10):  # noqa: UP036  旧解释器直接运行时给出明确提示（claude-agent-sdk 需要 3.10+）
    print("❌ 需要 Python 3.10 或更高版本")
    sys.exit(1)


def check_environment():
    """检查运行环境是否满足要求"""
    errors = []
    warnings = []

    # 检查必要的包
    required_packages = {
        "claude_agent_sdk": "pip install claude-agent-sdk",
        "dotenv": "pip install python-dotenv",
    }

    missing = []
    for package, install_cmd in required_packages.items():
        try:
            __import__(package)
        except ImportError:
            missing.append(f"  - {package}: {install_cmd}")

    if missing:
        errors.append("缺少必要的 Python 包：\n" + "\n".join(missing))
        errors.append("请运行：pip install -r requirements.txt")
        return errors, warnings

    # 默认提供方是 Claude 时，模型通过本机 Claude Code（订阅登录）调用，需能找到原生 claude 可执行文件；
    # GPT / 智谱不依赖 CLI，改为检查对应的 API Key
    from llm import LLMError, keys
    from llm.profiles import default_profile
    provider = default_profile().provider
    if provider == "claude":
        from llm.providers.claude import resolve_cli_path
        try:
            resolve_cli_path()
        except LLMError as e:
            errors.append(str(e))
    else:
        items = keys.missing_requirements(provider)
        if items:
            errors.append(f"默认提供方 {provider} 缺少：{'、'.join(items)}（请在设置页填写，或设置对应的环境变量）")

    return errors, warnings


def print_banner():
    """打印系统横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════════════╗
║                    🔬 多智能体研究系统                              ║
║                 Multi-Agent Research System v1.0                    ║
╠══════════════════════════════════════════════════════════════════════╣
║  智能体配置：                                                        ║
║  📋 规划师 → 🔍 研究员 → 🧐 分析师 → ✍️ 写作者 → 🔄 评审员(2-5次)  ║
║                                                                      ║
║  特性：并行搜索 | 多源研究 | 深度分析 | 2-5轮改进   | 文件通信     ║
╚══════════════════════════════════════════════════════════════════════╝
"""
    print(banner, flush=True)


def get_question() -> str:
    """获取用户的研究问题"""
    # 命令行参数模式
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"\n📌 研究问题（来自命令行）：{question}", flush=True)
        return question

    # 交互模式
    print("\n" + "─" * 70, flush=True)
    print("💬 请输入您想要研究的问题：", flush=True)
    print("   （可以是任何话题：技术、商业、科学、历史、社会等）", flush=True)
    print("─" * 70, flush=True)

    while True:
        try:
            question = input("\n🔍 您的问题 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 再见！")
            sys.exit(0)

        if question:
            return question
        else:
            print("❓ 请输入一个问题", flush=True)


def clarify(question: str) -> tuple:
    """交互式澄清（最多 4 轮，直接回车即开始研究）；返回 (补充说明, intent_meta)，澄清失败或中断时为 ("", None)。"""
    from agents.clarifier import ClarifierAgent, summary_to_brief
    from llm import LLMError

    agent = ClarifierAgent()
    try:
        result = agent.start(question)
        for _ in range(4):
            print(f"\n🗣️  澄清：{result['message']}", flush=True)
            if result["ready"]:
                break
            answer = input("   你的回答（直接回车开始研究）> ").strip()
            if not answer:
                break
            result = agent.reply(result["history"], answer)
    except LLMError as e:
        print(f"  [警告] 澄清失败，按原问题研究: {e}", flush=True)
        return "", None
    except (EOFError, KeyboardInterrupt):
        return "", None

    return summary_to_brief(result["summary"])


def display_final_report(report: str, workspace: str):
    """显示最终报告"""
    print(f"\n{'═'*70}", flush=True)
    print("📄 最终研究报告", flush=True)
    print(f"{'═'*70}", flush=True)

    # 限制控制台显示长度
    max_display = 5000
    if len(report) > max_display:
        print(report[:max_display], flush=True)
        print(f"\n... [报告过长，仅显示前 {max_display} 字符]", flush=True)
    else:
        print(report, flush=True)

    print(f"\n{'═'*70}", flush=True)
    print(f"📁 完整报告保存在：{workspace}", flush=True)

    # 询问是否要显示完整报告
    try:
        show_full = input("\n是否显示完整报告路径？(y/n) > ").strip().lower()
        if show_full == 'y':
            final_file = os.path.join(workspace, "09_final.md")
            print(f"\n完整报告文件：{final_file}", flush=True)
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    """主函数"""
    print_banner()

    # === 环境检查 ===
    print("🔎 检查运行环境...", flush=True)
    errors, warnings = check_environment()

    if errors:
        print("\n❌ 环境检查失败：", flush=True)
        for err in errors:
            print(f"  • {err}", flush=True)
        print("\n请解决以上问题后重新运行。", flush=True)
        sys.exit(1)

    if warnings:
        for warn in warnings:
            print(f"  ⚠️  {warn}", flush=True)

    print("✅ 环境检查通过", flush=True)

    # === 获取研究问题（交互模式下先澄清；命令行参数模式直接研究）===
    question = get_question()
    clarification, intent_meta = "", None
    if len(sys.argv) <= 1:
        clarification, intent_meta = clarify(question)

    # === 确认开始 ===
    print(f"\n{'─'*70}", flush=True)
    print(f"📌 将要研究：{question}", flush=True)
    if clarification:
        print(f"   补充说明：{clarification}", flush=True)
    from config import DEFAULT_DEPTH
    from llm.profiles import default_profile
    profile = default_profile()
    print(f"⚙️  设置：研究深度 {DEFAULT_DEPTH}，{profile.provider} 核心 {profile.core} / 辅助 {profile.support}",
          flush=True)
    print("⏱️  预计时间：约 45-80 分钟（取决于问题复杂度与改进轮数）", flush=True)

    try:
        confirm = input("\n确认开始研究？(y/n) > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "y"

    if confirm not in ('y', 'yes', '是', '确认', ''):
        print("已取消。", flush=True)
        sys.exit(0)

    # === 执行研究 ===
    start_time = time.time()

    try:
        from orchestrator import ResearchOrchestrator

        orchestrator = ResearchOrchestrator()
        report = orchestrator.run(question, intent_meta=intent_meta, clarification=clarification or None)

        elapsed = time.time() - start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        print(f"\n⏱️  总耗时：{minutes} 分 {seconds} 秒", flush=True)

        # 显示最终报告
        display_final_report(report, orchestrator.workspace)

    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\n⚠️  研究被用户中断（已运行 {elapsed:.0f} 秒）", flush=True)
        print("部分结果可能已保存在工作空间中。", flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 研究过程中出现错误：{str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
