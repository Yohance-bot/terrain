import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import { Users, Map as MapIcon, Activity, Smartphone } from 'lucide-react';

export default function Dashboard() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['stats'],
    queryFn: api.getStats,
    refetchInterval: 10000,
  });

  if (isLoading) return <div className="p-8">Loading stats...</div>;
  if (error) return <div className="p-8 text-destructive">Failed to load stats: {(error as Error).message}</div>;

  const cards = [
    { label: 'Total Territories', value: stats.total_territories, icon: MapIcon, color: 'text-blue-400' },
    { label: 'Active Owners', value: stats.active_owners, icon: Users, color: 'text-primary' },
    { label: 'Total Runs', value: stats.total_runs, icon: Activity, color: 'text-orange-400' },
    { label: 'Total Players', value: stats.total_accounts, icon: Users, color: 'text-purple-400' },
    { label: 'Total Devices', value: stats.total_devices, icon: Smartphone, color: 'text-gray-400' },
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground">Dashboard</h1>
        <p className="text-muted-foreground mt-2">Production Overview</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {cards.map((card) => (
          <div key={card.label} className="p-6 bg-card border border-border rounded-lg shadow-sm flex items-center gap-4">
            <div className={`p-4 bg-muted rounded-full ${card.color}`}>
              <card.icon className="w-8 h-8" />
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">{card.label}</p>
              <h3 className="text-3xl font-bold text-foreground mt-1">{card.value.toLocaleString()}</h3>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
