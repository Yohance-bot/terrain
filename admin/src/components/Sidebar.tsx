import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Map,
  Users,
  Activity,
  FileText,
  LogOut,
  SlidersHorizontal,
  Gamepad2,
  NotebookPen,
  Bot,
  UserRoundCog,
  Swords,
} from "lucide-react";
import { api, clearToken } from "../lib/api";
const links = [
  ["/", LayoutDashboard, "Overview"],
  ["/map", Map, "World map"],
  ["/simulation", Gamepad2, "Run simulator"],
  ["/players", Users, "Runners"],
  ["/runs", Activity, "Activity"],
  ["/social", Swords, "Social layer"],
  ["/audit", FileText, "Audit trail"],
  ["/notes", NotebookPen, "Field notes"],
  ["/assistant", Bot, "Ask Scout"],
  ["/team", UserRoundCog, "Team & profile"],
  ["/system", SlidersHorizontal, "System"],
] as const;
export default function Sidebar({ onLogout }: { onLogout: () => void }) {
  return (
    <aside className="sidebar">
      <div className="wordmark">
        ◈ TERRARUN<span>CONTROL CENTER</span>
      </div>
      <div className="workspace-label">
        <span className="status-dot" />
        Live environment<small>Bengaluru, India</small>
      </div>
      <nav>
        {links.map(([to, Icon, label]) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) => (isActive ? "active" : "")}
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <p>Your city. In motion.</p>
        <small>
          Authoritative server data
          <br />
          Refreshes while this tab is active
        </small>
        <button
          onClick={() => {
            void api
              .logout()
              .catch(() => undefined)
              .finally(() => {
                clearToken();
                onLogout();
              });
          }}
        >
          <LogOut size={16} />
          End session
        </button>
      </div>
    </aside>
  );
}
