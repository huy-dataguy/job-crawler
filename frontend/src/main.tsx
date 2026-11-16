import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { I18nProvider } from "./i18n";
import "./translations";
import AuthGate from "./AuthGate";
import "./index.css";

const qc = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 60_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <AuthGate>
        <I18nProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
        </I18nProvider>
      </AuthGate>
    </QueryClientProvider>
  </StrictMode>,
);
