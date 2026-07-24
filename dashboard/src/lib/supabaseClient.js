import { createClient } from "@supabase/supabase-js";

// These are the PUBLIC anon key values — safe to expose in frontend code.
// Read access is still gated by Supabase Auth (see the RLS policies in
// supabase/migrations/001_initial_schema.sql) — an unauthenticated
// visitor to this page sees nothing without logging in.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. Copy .env.example to .env and fill these in."
  );
}

export const supabase = createClient(supabaseUrl ?? "", supabaseAnonKey ?? "");
