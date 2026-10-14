import { locale, type Lang } from "../i18n";

/** 卷宗编号：CR-20261003-173109 */
export const crId = (sid: string) => `CR-${sid.replace("_", "-")}`;

export const f2 = (x: number) => x.toFixed(2);
export const minutes = (sec: number) => Math.round(sec / 60);

/** 后端时间是不带时区的本地时间（ISO），按本地时间解析。 */
const parse = (iso: string) => new Date(iso.length > 19 ? iso.slice(0, 19) : iso);

export const dateShort = (iso: string, lang: Lang) =>
  parse(iso).toLocaleDateString(locale(lang), { month: lang === "zh" ? "long" : "short", day: "numeric" });

export const clockTime = (iso: string) => {
  const d = parse(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

/** 来源链接来自网页抓取：只放行 http(s)，其他协议（如 javascript:）不生成可点的链接 */
export const webUrl = (url: string) => (/^https?:\/\//i.test(url) ? url : undefined);

export const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

/** 本地时间的 ISO 串（不带时区，和后端事件时间戳同一种写法），前端自己生成的时间也按它显示 */
export function localIso(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 兼容旧会话：问题与补充说明分开存之前，经澄清签发的研究把委托摘要接在问题后面（「补充说明：」段），
 *  这些会话及其续办任务的问题里仍带着它；列表与标题只显示问题本身。新会话没有这一段，原样返回 */
export const plainQuestion = (q: string) => q.split("\n\n补充说明：")[0];
