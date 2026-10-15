import { useState, useEffect } from "react";
import { Redirect, Route, Switch } from "wouter";
import { Toaster } from "sonner";
import { Shell } from "./components/shell/Shell";
import NewPage from "./pages/new/NewPage";
import CasePage, { CaseIndex } from "./pages/case/CasePage";
import CabinetPage from "./pages/cabinet/CabinetPage";
import DossierPage from "./pages/dossier/DossierPage";
import { research } from "./lib/api";

export default function App() {
  const [online, setOnline] = useState(false);

  useEffect(() => {
    research.health().then(() => setOnline(true)).catch(() => setOnline(false));
  }, []);

  return (
    <>
      <Toaster position="top-center" />
      <Shell online={online}>
        <Switch>
          <Route path="/"><Redirect to="/new" replace /></Route>
          <Route path="/research"><Redirect to="/new" replace /></Route>
          <Route path="/new"><NewPage /></Route>
          <Route path="/case"><CaseIndex /></Route>
          <Route path="/case/:taskId">{(p) => <CasePage key={p.taskId} taskId={p.taskId} />}</Route>
          <Route path="/cabinet"><CabinetPage /></Route>
          <Route path="/dossier/:sid/:tab?">{(p) => <DossierPage sid={p.sid} tab={p.tab} />}</Route>
          <Route><div className="wrap"><div className="empty"><h3>404</h3></div></div></Route>
        </Switch>
      </Shell>
    </>
  );
}
