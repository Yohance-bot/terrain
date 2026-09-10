import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Sidebar from "./components/Sidebar";
import LoginModal from "./components/LoginModal";
import Dashboard from "./pages/Dashboard";
import TerritoryMap from "./pages/Map";
import Players from "./pages/Players";
import Runs from "./pages/Runs";
import AuditLog from "./pages/AuditLog";
import Simulation from "./pages/Simulation";
import System from "./pages/System";
import Notes from "./pages/Notes";
import Team from "./pages/Team";
import Assistant from "./pages/Assistant";
import Social from "./pages/Social";
import { getToken } from "./lib/api";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
      refetchIntervalInBackground: false,
      staleTime: 10000,
    },
  },
});

export default function App() {
  const [token, setToken] = useState<string | null>(getToken());

  // Force re-render if token changes
  useEffect(() => {
    const handleStorageChange = () => setToken(getToken());
    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {!token ? (
          <LoginModal onLogin={(t) => setToken(t)} />
        ) : (
          <div className="flex h-screen bg-background text-foreground overflow-hidden">
            <Sidebar
              onLogout={() => {
                queryClient.clear();
                setToken(null);
              }}
            />
            <main className="flex-1 h-full min-h-0 overflow-auto relative flex flex-col">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/map" element={<TerritoryMap />} />
                <Route path="/simulation" element={<Simulation />} />
                <Route path="/notes" element={<Notes />} />
                <Route path="/team" element={<Team />} />
                <Route path="/assistant" element={<Assistant />} />
                <Route path="/system" element={<System />} />
                <Route path="/players" element={<Players />} />
                <Route path="/runs" element={<Runs />} />
                <Route path="/social" element={<Social />} />
                <Route path="/audit" element={<AuditLog />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </div>
        )}
      </BrowserRouter>
    </QueryClientProvider>
  );
}
