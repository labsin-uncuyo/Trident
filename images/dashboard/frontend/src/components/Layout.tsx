import { NavLink, Outlet } from 'react-router-dom';
import {
  Network,
  Bot,
  ShieldAlert,
  Wifi,
  FolderOpen,
  Activity,
} from 'lucide-react';
import { ContainerStatusBar } from './ContainerStatusBar';

const navItems = [
  { to: '/', icon: Network, label: 'Topology' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/alerts', icon: ShieldAlert, label: 'Alerts' },
  { to: '/traffic', icon: Wifi, label: 'Traffic' },
  { to: '/runs', icon: FolderOpen, label: 'Runs' },
];

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-64 flex-col border-r border-trident-border bg-trident-surface">
        {/* Logo */}
        <div className="flex items-center gap-3 border-b border-trident-border px-5 py-4">
          <img src="/trident.svg" alt="Trident" className="h-8 w-8" />
          <div>
            <h1 className="font-heading text-lg font-bold tracking-tight text-white">
              TRIDENT
            </h1>
            <p className="text-[10px] uppercase tracking-widest text-trident-muted">
              Dashboard
            </p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `nav-link ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Status bar at bottom */}
        <ContainerStatusBar />
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto bg-trident-bg p-6">
        <Outlet />
      </main>
    </div>
  );
}
