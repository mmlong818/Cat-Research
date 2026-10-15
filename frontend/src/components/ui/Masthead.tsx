import type { ReactNode } from "react";

/** 报头：衬线大标题 + 副信息 + 右侧工具，下接双线。 */
export function Masthead({ title, children, tools }: { title: string; children?: ReactNode; tools?: ReactNode }) {
  return (
    <>
      <div className="mast">
        <h1>{title}</h1>
        {children}
        {tools && <div className="tools">{tools}</div>}
      </div>
      <div className="double" />
    </>
  );
}
