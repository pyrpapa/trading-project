// Vercel serverless function -- triggers live/close_position.py (via the
// close-position.yml GitHub Actions workflow) for one ticker, closing
// its ENTIRE position (pyramided stacks included -- see that script's
// own docstring, no partial close exists). Unlike api/quotes.js
// (read-only market data, left open), this one submits a real order --
// paper for now, but the same code path a real-money account would use
// -- so it's gated behind an actual logged-in dashboard session, not
// left open to anyone who finds the URL.
//
// Two credentials involved, both server-side only, both set as plain
// (non-VITE_-prefixed) Vercel project environment variables:
//   - VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY (already set for the
//     dashboard itself -- reused here just to verify the caller's
//     session server-side, not to bypass RLS or read data).
//   - GITHUB_DISPATCH_TOKEN -- a fine-grained GitHub PAT, Actions
//     read/write only, scoped to this repo. Deliberately a SEPARATE
//     token from cron-job.org's, even though the required scope is
//     identical, so the two can be rotated/revoked independently.
//
// POST /api/sell  { ticker: "SPXL", dryRun: false }
// Header: Authorization: Bearer <supabase access_token>

import { createClient } from "@supabase/supabase-js";

const REPO = "pyrpapa/trading-project";

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "POST only" });
  }

  const { ticker, dryRun } = req.body || {};
  if (!ticker) {
    return res.status(400).json({ error: "ticker required" });
  }

  const authHeader = req.headers.authorization || "";
  const accessToken = authHeader.replace(/^Bearer\s+/i, "");
  if (!accessToken) {
    return res.status(401).json({ error: "Missing Authorization header -- not logged in?" });
  }

  const supabaseUrl = process.env.VITE_SUPABASE_URL;
  const supabaseAnonKey = process.env.VITE_SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseAnonKey) {
    return res.status(500).json({ error: "Supabase env vars not configured on the server" });
  }

  const supabase = createClient(supabaseUrl, supabaseAnonKey);
  const { data: userData, error: userError } = await supabase.auth.getUser(accessToken);
  if (userError || !userData?.user) {
    return res.status(401).json({ error: "Invalid or expired session -- log in again and retry" });
  }

  const dispatchToken = process.env.GITHUB_DISPATCH_TOKEN;
  if (!dispatchToken) {
    return res.status(500).json({ error: "GITHUB_DISPATCH_TOKEN not configured on the server" });
  }

  try {
    const resp = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/close-position.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${dispatchToken}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: { ticker, dry_run: dryRun ? "true" : "false" },
        }),
      }
    );

    if (resp.status !== 204) {
      const text = await resp.text();
      return res.status(resp.status).json({ error: `GitHub API error (${resp.status}): ${text}` });
    }

    return res.status(200).json({ ok: true });
  } catch (e) {
    return res.status(500).json({ error: String(e) });
  }
}
