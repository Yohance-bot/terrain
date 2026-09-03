import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import { format } from 'date-fns';

export default function Players() {
  const [page, setPage] = useState(0);
  const limit = 50;
  
  const { data, isLoading, error } = useQuery({
    queryKey: ['players', page],
    queryFn: () => api.getPlayers(page * limit, limit),
  });

  if (error) return <div className="p-8 text-destructive">Error: {(error as Error).message}</div>;

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-foreground">Players</h1>
          <p className="text-muted-foreground mt-2">Accounts and Devices</p>
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-muted border-b border-border text-muted-foreground text-sm uppercase tracking-wider">
                <th className="p-4 font-medium">Display Name</th>
                <th className="p-4 font-medium">Role</th>
                <th className="p-4 font-medium">Distance (m)</th>
                <th className="p-4 font-medium">Territories Led</th>
                <th className="p-4 font-medium">Joined</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-muted-foreground">Loading...</td>
                </tr>
              ) : data?.items.map((player: any) => (
                <tr key={player.account_id} className="hover:bg-muted/50 transition-colors">
                  <td className="p-4">
                    <div className="font-medium text-foreground">{player.display_name}</div>
                    <div className="text-xs text-muted-foreground font-mono mt-1">{player.account_id}</div>
                  </td>
                  <td className="p-4">
                    <span className={`inline-flex px-2 py-1 text-xs rounded-full ${
                      player.role === 'developer' ? 'bg-purple-500/20 text-purple-400' : 'bg-primary/20 text-primary'
                    }`}>
                      {player.role}
                    </span>
                  </td>
                  <td className="p-4 text-foreground font-mono">{player.total_distance_m.toFixed(1)}</td>
                  <td className="p-4 text-foreground">{player.territories_led}</td>
                  <td className="p-4 text-muted-foreground text-sm">
                    {format(new Date(player.created_at), 'MMM d, yyyy HH:mm')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        
        {data && (
          <div className="p-4 border-t border-border flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Showing {page * limit + 1} to Math.min((page + 1) * limit, data.total) of {data.total}
            </span>
            <div className="space-x-2">
              <button 
                disabled={page === 0}
                onClick={() => setPage(p => Math.max(0, p - 1))}
                className="px-3 py-1 bg-muted text-foreground rounded disabled:opacity-50 hover:bg-border transition-colors"
              >
                Previous
              </button>
              <button 
                disabled={(page + 1) * limit >= data.total}
                onClick={() => setPage(p => p + 1)}
                className="px-3 py-1 bg-muted text-foreground rounded disabled:opacity-50 hover:bg-border transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
