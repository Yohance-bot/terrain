import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Sidebar from './components/Sidebar';
import LoginModal from './components/LoginModal';
import Dashboard from './pages/Dashboard';
import TerritoryMap from './pages/Map';
import Players from './pages/Players';
import Runs from './pages/Runs';
import AuditLog from './pages/AuditLog';
import { getToken } from './lib/api';

const queryClient = new QueryClient();

export default function App() {
  const [token, setToken] = useState<string | null>(getToken());

  // Force re-render if token changes
  useEffect(() => {
    const handleStorageChange = () => setToken(getToken());
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {!token ? (
          <LoginModal onLogin={(t) => setToken(t)} />
        ) : (
          <div className="flex h-screen bg-background text-foreground overflow-hidden">
            <Sidebar onLogout={() => setToken(null)} />
            <main className="flex-1 h-full min-h-0 overflow-auto relative flex flex-col">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/map" element={<TerritoryMap />} />
                <Route path="/players" element={<Players />} />
                <Route path="/runs" element={<Runs />} />
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
