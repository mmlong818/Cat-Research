import { useState } from "react";
import { Link } from "wouter";
import { Masthead } from "../../components/ui/Masthead";
import { Icon } from "../../components/ui/Icon";
import { crId } from "../../lib/format";
import { useT } from "../../i18n";
import { useDossier, type Dossier } from "./useDossier";
import { useDerived } from "./useDerived";
import { useBlocks } from "./useBlocks";
import { DossierIndex, DossierMast, TABS, type Tab } from "./DossierChrome";
import { Cover } from "./Cover";
import { TextTab } from "./TextTab";
import { EvidenceTab } from "./EvidenceTab";
import { VerdictTab } from "./VerdictTab";
import { ProcessTab } from "./ProcessTab";
import { FilesTab } from "./FilesTab";
import "./dossier.css";
import "./tabs.css";
import "./gloss.css";

function DossierView({ d, tab }: { d: Dossier; tab: Tab }) {
  const x = useDerived(d);
  const [sec, setSec] = useState(0);
  const blocks = useBlocks(tab === "text" ? x.body : null, x.claims, true);
  const body = {
    cover: null,
    text: <TextTab blocks={blocks} claims={x.claims} sid={d.sid} onSection={setSec} />,
    evidence: <EvidenceTab d={d} x={x} />,
    verdict: <VerdictTab d={d} />,
    process: <ProcessTab d={d} x={x} />,
    files: <FilesTab d={d} x={x} />,
  }[tab];
  return (
    <div className="wrap dossier">
      <DossierMast d={d} />
      {tab === "cover" ? <Cover d={d} x={x} /> : (
        <div className="dos">
          <DossierIndex d={d} x={x} tab={tab} sec={sec} />
          <div className="dos-body">{body}</div>
        </div>
      )}
    </div>
  );
}

function Missing({ sid, message }: { sid: string; message: string }) {
  const { t } = useT();
  return (
    <div className="empty">
      <Icon name="archive" />
      <h3>{t("dossier.missing.title")}</h3>
      <p>{t("dossier.missing.body", { id: crId(sid), msg: message })}</p>
      <div className="btns"><Link className="btn btn--primary" href="/cabinet">{t("dossier.missing.back")}</Link></div>
    </div>
  );
}

/** 卷宗页 /dossier/:sid/:tab?：封面、正文、证据、裁决、过程、附件；数据全部来自真实接口 */
export default function DossierPage({ sid, tab }: { sid: string; tab?: string }) {
  const { t } = useT();
  const state = useDossier(sid);
  const cur = (TABS as readonly string[]).includes(tab ?? "") ? (tab as Tab) : "cover";
  if (state.status === "ready") return <DossierView d={state.data} tab={cur} />;
  return (
    <div className="wrap dossier">
      <Masthead title={t("dossier.title")}><span className="wk">{crId(sid)}</span></Masthead>
      {state.status === "loading"
        ? <p className="hint dossier-loading">{t("dossier.loading")}</p>
        : <Missing sid={sid} message={state.message} />}
    </div>
  );
}
