import React from "react";
import { createRoot } from "react-dom/client";
import App from "./app/App.jsx";
import "./app/app.css";
import "./features/trace/trace.css";

createRoot(document.getElementById("app")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
