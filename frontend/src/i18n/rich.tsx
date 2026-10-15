import { Fragment, type ReactNode } from "react";

/** 把译文模板里的 {{名}} 换成 React 节点（数字要包进等宽 span，加粗要包进 strong 时用）。 */
export function rich(template: string, vars: Record<string, ReactNode>): ReactNode {
  const parts = template.split(/\{\{(\w+)\}\}/);
  return parts.map((p, i) => <Fragment key={i}>{i % 2 ? (vars[p] ?? `{{${p}}}`) : p}</Fragment>);
}

export const N = ({ children }: { children: ReactNode }) => <span className="num">{children}</span>;

/** 中英混排的文件名：只把字母数字段放进等宽字体，汉字不进等宽字体 */
export const Mixed = ({ text }: { text: string }) => (
  <>{text.split(/([A-Za-z0-9._-]+)/).map((p, i) => (i % 2 ? <span key={i} className="num">{p}</span> : p))}</>
);
