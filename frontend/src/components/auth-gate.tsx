// frontend/src/components/auth-gate.tsx
import { useEffect, useState, type ReactNode } from "react";

import { useConfig } from "@/components/config-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getAuthToken, setAuthToken } from "@/lib/auth-token";

/**
 * Gates the app behind the optional bearer token. When the backend requires auth (config
 * `auth_required`) and no token is stored, shows a login form instead of the app — so no data
 * query fires an inevitable 401. Listens for `maki:unauthorized` (emitted by apiFetch on a 401) to
 * drop back to the form when a token goes stale.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { auth_required } = useConfig();
  const [token, setToken] = useState<string | null>(() => getAuthToken());
  const [entry, setEntry] = useState("");

  useEffect(() => {
    const onUnauth = () => setToken(null);
    window.addEventListener("maki:unauthorized", onUnauth);
    return () => window.removeEventListener("maki:unauthorized", onUnauth);
  }, []);

  if (!auth_required || token) return <>{children}</>;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!entry) return;
    setAuthToken(entry);
    setToken(entry);
  };

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4">
        <div className="space-y-1.5">
          <h1 className="text-lg font-semibold">Sign in</h1>
          <p className="text-sm text-muted-foreground">
            This instance requires an access token. Paste the value of{" "}
            <code className="font-mono">MAKI_AUTH_TOKEN</code>.
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="auth-token">Access token</Label>
          <Input
            id="auth-token"
            type="password"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            autoFocus
          />
        </div>
        <Button type="submit" className="w-full">
          Sign in
        </Button>
      </form>
    </div>
  );
}
