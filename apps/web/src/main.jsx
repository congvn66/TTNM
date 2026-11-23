import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/plus-jakarta-sans";
import App from "./app/App.jsx";
import "./app/styles/tokens.css";
import "./app/styles/themes.css";
import "./app/app.css";
import "./features/trace/trace.css";

createRoot(document.getElementById("app")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
