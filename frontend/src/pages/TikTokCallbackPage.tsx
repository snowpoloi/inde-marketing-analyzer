import { useEffect, useState } from "react";
import { api } from "../api/client";

export function TikTokCallbackPage() {
  const [message, setMessage] = useState("Connecting TikTok Ads...");
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const error = params.get("error") || params.get("error_description");
    const authCode = params.get("auth_code");
    const state = params.get("state");
    if (error) {
      setMessage(`TikTok authorization was not completed: ${error}`);
      return;
    }
    if (!authCode || !state) {
      setMessage("TikTok did not return an authorization code. Return to Settings and start the connection again.");
      return;
    }
    api
      .completeTikTokAuthorization(authCode, state)
      .then(() => {
        setConnected(true);
        setMessage("TikTok Ads is connected. You can now return to Settings and run a sync.");
      })
      .catch((err) => setMessage(err instanceof Error ? err.message : "Could not connect TikTok Ads."));
  }, []);

  return (
    <main className="content">
      <div className="page-stack">
        <header className="page-header">
          <div>
            <h1>TikTok Ads</h1>
            <p>{message}</p>
          </div>
        </header>
        <button className="primary-action compact" onClick={() => window.location.replace(`${window.location.origin}/#settings`)}>
          {connected ? "Return to Settings" : "Open Settings"}
        </button>
      </div>
    </main>
  );
}
