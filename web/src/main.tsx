import React from "react";
import ReactDOM from "react-dom/client";
import { Agentation } from "agentation";
import "@fontsource-variable/geist";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    {import.meta.env.DEV ? <Agentation /> : null}
  </React.StrictMode>,
);
