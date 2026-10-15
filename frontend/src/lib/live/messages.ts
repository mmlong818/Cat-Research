import type { DirectiveMsg, MsgState } from "./model";

// 补充指令的三段回执。回放缓冲有上限，长任务重连时可能缺帧：只收到 applied 没收到 ack 时按"已读取并已用上"处理

const RANK: Record<MsgState, number> = { failed: 0, sending: 1, queued: 2, ack: 3, applied: 4 };
let nextId = 1;

const fresh = (text: string, state: MsgState, at: string, gate: string | null = null): DirectiveMsg =>
  ({ id: nextId++, text, state, seen: true, gate, agents: [], sentAt: at });

const replace = (list: DirectiveMsg[], i: number, m: DirectiveMsg) => list.map((x, k) => (k === i ? m : x));

/** 本地发出（POST 还没回来） */
export function addSending(list: DirectiveMsg[], text: string, at: string): [DirectiveMsg[], number] {
  const m = { ...fresh(text, "sending", at), seen: false };
  return [[...list, m], m.id];
}

/** POST 成功 / 失败 */
export function markPosted(list: DirectiveMsg[], id: number, error?: string): DirectiveMsg[] {
  return list.map((m) => {
    if (m.id !== id || RANK[m.state] > RANK.queued) return m;
    return error ? { ...m, state: "failed", error } : { ...m, state: "queued" };
  });
}

/** user_message_queued：对上本地还没确认过的同文消息，对不上（如重连回放）就新增一条 */
export function onQueued(list: DirectiveMsg[], text: string, at: string): DirectiveMsg[] {
  const i = list.findIndex((m) => m.text === text && !m.seen && m.state !== "failed");
  if (i < 0) return [...list, fresh(text, "queued", at)];
  const m = list[i];
  return replace(list, i, { ...m, seen: true, state: RANK[m.state] < RANK.queued ? "queued" : m.state });
}

/** user_message_ack：这一批在某个检查点被读取 */
export function onAck(list: DirectiveMsg[], texts: string[], gate: string, at: string): DirectiveMsg[] {
  return texts.reduce((acc, text) => {
    const i = acc.findIndex((m) => m.text === text && RANK[m.state] < RANK.ack && m.state !== "failed");
    if (i < 0) return [...acc, fresh(text, "ack", at, gate)];
    return replace(acc, i, { ...acc[i], state: "ack", gate, seen: true });
  }, list);
}

/** user_message_applied：这一批写进了某个智能体的提示词；同一批可以多次到达，智能体逐条累加 */
export function onApplied(list: DirectiveMsg[], texts: string[], gate: string, agents: string[], at: string) {
  return texts.reduce((acc, text) => {
    let i = acc.findIndex((m) => m.text === text && m.gate === gate);
    if (i < 0) i = acc.findIndex((m) => m.text === text && RANK[m.state] < RANK.ack && m.state !== "failed");
    if (i < 0) return [...acc, { ...fresh(text, "applied", at, gate), agents }];
    const m = acc[i];
    const merged = [...m.agents, ...agents.filter((a) => !m.agents.includes(a))];
    return replace(acc, i, { ...m, state: "applied", gate, seen: true, agents: merged });
  }, list);
}

/** 快照重建时保留还没得到服务端确认的本地消息，其余由回放事件重建 */
export const keepLocal = (list: DirectiveMsg[]) => list.filter((m) => !m.seen);
