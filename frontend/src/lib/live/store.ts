import { useEffect, useState, useSyncExternalStore } from "react";
import { ApiError, research } from "../api";
import { localIso } from "../format";
import { initState, type CaseState } from "./model";
import { reduce, type StreamEvent } from "./reduce";
import { addSending, markPosted } from "./messages";
import { TaskStream } from "./stream";

/** 运行中任务的共享状态：每个任务只连一条 SSE，案头、顶栏与办案记录读同一份 */
class LiveStore {
  private states = new Map<string, CaseState>();
  private conns = new Map<string, TaskStream>();
  private listeners = new Set<() => void>();
  private version = 0;

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getVersion = () => this.version;

  get = (taskId: string) => this.states.get(taskId);

  all = () => [...this.states.values()];

  update(taskId: string, fn: (s: CaseState) => CaseState) {
    this.states.set(taskId, fn(this.states.get(taskId) ?? initState(taskId)));
    this.version += 1;
    this.listeners.forEach((l) => l());
  }

  private dispatch = (taskId: string, ev: StreamEvent) => {
    this.update(taskId, (s) => reduce(s, ev));
    if (ev.type === "end") this.conns.delete(taskId);
  };

  /** 开始跟踪一个任务（重复调用无副作用）；任务不存在时标记为 missing，不连 SSE */
  watch(taskId: string) {
    if (this.conns.has(taskId) || this.states.get(taskId)?.ended) return;
    if (!this.states.has(taskId)) this.update(taskId, (s) => s);
    this.conns.set(taskId, new TaskStream(taskId, (ev) => this.dispatch(taskId, ev)));
  }

  /** 连不上时用状态接口确认任务是否还存在（404 = 已删除或编号不对） */
  async verify(taskId: string) {
    try {
      await research.status(taskId);
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 404) return;
      this.conns.get(taskId)?.close();
      this.conns.delete(taskId);
      this.update(taskId, (s) => ({ ...s, status: "missing", ended: true }));
    }
  }

  async pause(taskId: string) {
    await research.pause(taskId);
    this.update(taskId, (s) => ({ ...s, pauseRequested: true, resuming: false }));
  }

  async resume(taskId: string) {
    await research.resume(taskId);
    // 已停在检查点上：等 resumed 事件；还没走到检查点（正在暂停）：恢复请求直接生效，不会再有事件
    this.update(taskId, (s) => ({ ...s, pauseRequested: false, resuming: s.lastPause === "paused" }));
  }

  async stop(taskId: string) {
    this.update(taskId, (s) => ({ ...s, stopping: true }));
    try {
      await research.stop(taskId);
    } catch (e) {
      this.update(taskId, (s) => ({ ...s, stopping: false }));
      throw e;
    }
  }

  async decide(taskId: string, choice: "continue" | "stop") {
    try {
      await research.loopDecision(taskId, choice);
    } finally { // 成功由 resolved 事件收尾；409（已决定或已超时）时这张签批单也不再有意义
      this.update(taskId, (s) => ({ ...s, decision: null }));
    }
  }

  async send(taskId: string, text: string) {
    let id = 0;
    this.update(taskId, (s) => {
      const [messages, newId] = addSending(s.messages, text, localIso());
      id = newId;
      return { ...s, messages };
    });
    try {
      await research.inject(taskId, text);
      this.update(taskId, (s) => ({ ...s, messages: markPosted(s.messages, id) }));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.update(taskId, (s) => ({ ...s, messages: markPosted(s.messages, id, msg) }));
      throw e;
    }
  }
}

export const live = new LiveStore();

/** 订阅全部任务状态的变化（返回值只用来触发重渲染） */
export const useLiveVersion = () => useSyncExternalStore(live.subscribe, live.getVersion);

/** 跟踪并读取一个任务 */
export function useLive(taskId: string | null): CaseState | undefined {
  useLiveVersion();
  useEffect(() => {
    if (!taskId) return;
    live.watch(taskId);
    void live.verify(taskId);
  }, [taskId]);
  return taskId ? live.get(taskId) : undefined;
}

/** 每隔 ms 毫秒刷新一次的当前时间（倒计时、已办分钟数） */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
