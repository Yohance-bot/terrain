import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Map as MapIcon, Users, Activity, FileText, LogOut } from 'lucide-react';
import { clearToken } from '../lib/api';

export default function Sidebar({ onLogout }: { onLogout: () => void }) {
  const handleLogout = () => {
    clearToken();
    onLogout();
  };

  const navItems = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/map', icon: MapIcon, label: 'Territory Map' },
    { to: '/players', icon: Users, label: 'Players' },
    { to: '/runs', icon: Activity, label: 'Runs' },
    { to: '/audit', icon: FileText, label: 'Audit Log' },
  ];

  return (
    <aside className="w-64 border-r border-border bg-card flex flex-col">
      <div className="p-6 border-b border-border">
        <h1 className="text-xl font-bold text-primary flex items-center gap-2">
          <Activity className="w-6 h-6" />
          Run Admin
        </h1>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md transition-colors ${
                isActive
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`
            }
          >
            <item.icon className="w-5 h-5" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-border">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2 w-full text-left text-muted-foreground hover:text-destructive transition-colors rounded-md hover:bg-muted"
        >
          <LogOut className="w-5 h-5" />
          Clear Token & Exit
        </button>
      </div>
    </aside>
  );
}
