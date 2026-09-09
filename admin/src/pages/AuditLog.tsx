import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { format } from "date-fns";

export default function AuditLog() {
  const [page, setPage] = useState(0);
  const limit = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit-events", page],
    refetchInterval: 15000,
    queryFn: () => api.getAuditEvents(page * limit, limit),
  });

  if (error)
    return (
      <div className="p-8 text-destructive">
        Error: {(error as Error).message}
      </div>
    );

  return (
    <div className="page">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground">Audit Log</h1>
        <p className="text-muted-foreground mt-2">
          Immutable operational activity feed
        </p>
      </div>

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-muted border-b border-border text-muted-foreground text-sm uppercase tracking-wider">
                <th className="p-4 font-medium">Timestamp</th>
                <th className="p-4 font-medium">Action</th>
                <th className="p-4 font-medium">Actor</th>
                <th className="p-4 font-medium">Target</th>
                <th className="p-4 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {isLoading ? (
                <tr>
                  <td
                    colSpan={5}
                    className="p-8 text-center text-muted-foreground"
                  >
                    Loading...
                  </td>
                </tr>
              ) : (
                data?.items.map((event: any) => (
                  <tr
                    key={event.id}
                    className="hover:bg-muted/50 transition-colors"
                  >
                    <td className="p-4 text-muted-foreground text-sm whitespace-nowrap">
                      {format(
                        new Date(event.created_at),
                        "yyyy-MM-dd HH:mm:ss",
                      )}
                    </td>
                    <td className="p-4">
                      <span className="inline-flex px-2 py-1 text-xs rounded bg-blue-500/20 text-blue-400 font-mono">
                        {event.action}
                      </span>
                    </td>
                    <td className="p-4">
                      <div className="text-sm font-medium text-foreground">
                        {event.actor_kind}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono mt-1">
                        {event.actor_ref || "system"}
                      </div>
                    </td>
                    <td className="p-4">
                      <div className="text-sm text-foreground">
                        {event.target_type}
                      </div>
                      <div
                        className="text-xs text-muted-foreground font-mono mt-1 truncate max-w-xs"
                        title={event.target_ref}
                      >
                        {event.target_ref}
                      </div>
                    </td>
                    <td
                      className="p-4 text-sm text-muted-foreground max-w-md truncate"
                      title={event.reason || ""}
                    >
                      {event.reason || "-"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {data && (
          <div className="p-4 border-t border-border flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Showing {data.total ? page * limit + 1 : 0} to{" "}
              {Math.min((page + 1) * limit, data.total)} of {data.total}
            </span>
            <div className="space-x-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="px-3 py-1 bg-muted text-foreground rounded disabled:opacity-50 hover:bg-border transition-colors"
              >
                Previous
              </button>
              <button
                disabled={(page + 1) * limit >= data.total}
                onClick={() => setPage((p) => p + 1)}
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
