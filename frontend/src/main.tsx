import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/app.css";
import "./styles/components.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Failed to find the root element");
}

const root = ReactDOM.createRoot(rootElement);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
