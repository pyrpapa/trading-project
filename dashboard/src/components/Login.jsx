import { useState } from "react";
import { supabase } from "../lib/supabaseClient.js";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) setError(error.message);
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          width: 320,
          padding: 32,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
        }}
      >
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            letterSpacing: "0.08em",
            color: "var(--accent)",
            marginBottom: 4,
          }}
        >
          ● CONSOLE
        </div>
        <h1
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 20,
            fontWeight: 600,
            margin: "0 0 24px 0",
          }}
        >
          Sign in
        </h1>

        <label style={labelStyle}>Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={inputStyle}
        />

        <label style={{ ...labelStyle, marginTop: 16 }}>Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          style={inputStyle}
        />

        {error && (
          <div style={{ color: "var(--negative)", fontSize: 13, marginTop: 12 }}>{error}</div>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            marginTop: 24,
            padding: "10px 0",
            background: "var(--accent)",
            color: "var(--bg)",
            border: "none",
            borderRadius: "var(--radius)",
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>

        <div style={{ marginTop: 16, fontSize: 12, color: "var(--text-faint)" }}>
          Your login is created in the Supabase dashboard under
          Authentication → Users. This console has no public signup.
        </div>
      </form>
    </div>
  );
}

const labelStyle = {
  display: "block",
  fontSize: 12,
  color: "var(--text-muted)",
  marginBottom: 6,
};

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  color: "var(--text-primary)",
  fontSize: 14,
};
