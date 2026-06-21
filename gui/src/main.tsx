import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// Dark theme tuned to the original tester palette (deep navy, bright blue).
const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: "#3b82f6" },
    background: { default: "#0c111b", paper: "#0f1623" },
    divider: "#1f2a3d",
    text: { primary: "#c9d4e3", secondary: "#6b7a90" },
  },
  shape: { borderRadius: 8 },
  typography: { fontSize: 13 },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>,
);
