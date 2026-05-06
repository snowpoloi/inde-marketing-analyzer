import { FormEvent, useState } from "react";
import { LockKeyhole, Store } from "lucide-react";
import { api, setToken } from "../api/client";

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState("admin@inde.gr");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await api.login(email, password);
      setToken(result.access_token);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-panel" onSubmit={submit}>
        <div className="login-brand">
          <Store size={24} />
          <div>
            <strong>INDE Marketing Analyzer</strong>
            <span>Admin access</span>
          </div>
        </div>
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" />
        </label>
        <label>
          Password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
          />
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <button className="primary-action" disabled={loading}>
          <LockKeyhole size={18} />
          {loading ? "Signing in" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

