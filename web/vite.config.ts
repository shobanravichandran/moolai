import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to the local FastAPI server (uvicorn moolai.api:app --port 8020). 127.0.0.1, not
// localhost: Node resolves localhost to ::1 first, and uvicorn listens on IPv4 only.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: { "/api": "http://127.0.0.1:8020" },
  },
});
