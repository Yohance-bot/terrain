import React, { useState } from 'react';
import { setToken as saveToken } from '../lib/api';

export default function LoginModal({ onLogin }: { onLogin: (token: string) => void }) {
  const [input, setInput] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim()) {
      saveToken(input.trim());
      onLogin(input.trim());
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md bg-card border border-border rounded-lg shadow-xl overflow-hidden">
        <div className="p-6 border-b border-border">
          <h2 className="text-2xl font-bold text-foreground">Run Admin Console</h2>
          <p className="text-sm text-muted-foreground mt-2">
            This is a temporary MVP authentication mechanism. Do not use this in a public deployment.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Admin Operations Token
            </label>
            <input
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              className="w-full px-3 py-2 bg-input border border-border rounded-md text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="Enter X-Admin-Token"
              autoFocus
            />
          </div>
          <button
            type="submit"
            className="w-full py-2 bg-primary text-primary-foreground font-semibold rounded-md hover:bg-primary/90 transition-colors"
          >
            Authenticate
          </button>
        </form>
      </div>
    </div>
  );
}
