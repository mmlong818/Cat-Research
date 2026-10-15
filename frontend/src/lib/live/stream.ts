import { research } from "../api";
import type { StreamEvent } from "./reduce";

// 任务进度 SSE：断线后指数退避重连（上限 30 秒）。每次（重）连接服务端先发 snapshot 再回放缓冲事件，
// 收到 end（后台线程已退出）后关闭、不再重连。disconnected 不是服务端事件，是这里在重试前合成的。

const MAX_DELAY_MS = 30_000;

export class TaskStream {
  private es: EventSource | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private closed = false;

  constructor(private readonly taskId: string, private readonly onEvent: (e: StreamEvent) => void) {
    this.open();
  }

  close() {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.es?.close();
    this.es = null;
  }

  private open() {
    const es = research.stream(this.taskId);
    this.es = es;
    es.onmessage = (m) => {
      let ev: StreamEvent;
      try { ev = JSON.parse(m.data); } catch { return; }
      if (ev.type === "snapshot") this.attempt = 0;
      if (ev.type === "end") this.close(); // error/completed 之后还会有 end，等它再关
      this.onEvent(ev);
    };
    // 浏览器自带重连没有退避且不通知我们：关掉，自己按退避重连
    es.onerror = () => {
      es.close();
      if (this.closed) return;
      const delay = Math.min(1000 * 2 ** this.attempt, MAX_DELAY_MS);
      this.attempt += 1;
      this.onEvent({ type: "disconnected", data: { retry_in: Math.round(delay / 1000) } });
      this.timer = setTimeout(() => { if (!this.closed) this.open(); }, delay);
    };
  }
}
