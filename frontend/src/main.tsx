import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/forms.css";
import "./index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { I18nProvider } from "./i18n";
import { applyTheme, loadTheme } from "./lib/theme";

applyTheme(loadTheme()); // 首帧前定主题，避免先闪一下浅色

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>
);
