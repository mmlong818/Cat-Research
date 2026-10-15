import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "wouter";
import { Topbar } from "./Topbar";
import { Desk } from "./Desk";
import { DeskProvider } from "./useDesk";
import { NARROW, useMedia } from "./useMedia";
import "./shell.css";

const COLLAPSED_KEY = "cr.deskCollapsed";

const OpenDesk = createContext<() => void>(() => {});
/** 让页面里的"去案头处理"展开案头（窄屏打开抽屉） */
export const useOpenDesk = () => useContext(OpenDesk);

/** 外壳：顶栏 + 案头 + 主区。主区是滚动容器，换页时回到顶部。 */
export function Shell({ online, children }: { online: boolean; children: ReactNode }) {
  const narrow = useMedia(NARROW);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === "1");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [location] = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setDrawerOpen(false);
    mainRef.current?.scrollTo(0, 0);
  }, [location]);

  const toggle = useCallback(() => {
    if (narrow) { setDrawerOpen((v) => !v); return; }
    setCollapsed((v) => {
      localStorage.setItem(COLLAPSED_KEY, v ? "0" : "1");
      return !v;
    });
  }, [narrow]);
  const close = useCallback(() => setDrawerOpen(false), []);
  const open = useCallback(() => {
    if (narrow) { setDrawerOpen(true); return; }
    localStorage.setItem(COLLAPSED_KEY, "0");
    setCollapsed(false);
  }, [narrow]);
  const mini = !narrow && collapsed;

  return (
    <DeskProvider>
      <div className="app">
        <Topbar online={online} onToggleDesk={toggle} />
        <div className={`shell${mini ? " collapsed" : ""}`}>
          <Desk narrow={narrow} collapsed={mini} drawerOpen={drawerOpen} onToggle={toggle} onClose={close} />
          <main className="shell-main" ref={mainRef}><OpenDesk.Provider value={open}>{children}</OpenDesk.Provider></main>
        </div>
      </div>
    </DeskProvider>
  );
}
