import { useEffect, useState } from "react";
import { supabase } from "./lib/supabaseClient.js";
import Login from "./components/Login.jsx";
import StatusBar from "./components/StatusBar.jsx";
import SummaryCards from "./components/SummaryCards.jsx";
import EquityChart from "./components/EquityChart.jsx";
import PositionsTable from "./components/PositionsTable.jsx";
import SignalsFeed from "./components/SignalsFeed.jsx";
import BacktestComparison from "./components/BacktestComparison.jsx";

export default function App() {
  const [session, setSession] = useState(undefined); // undefined = loading, null = signed out
  const [data, setData] = useState({
    snapshots: [],
    openTrades: [],
    closedTrades: [],
    signals: [],
    runs: [],
  });
  const [loadingData, setLoadingData] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => setSession(session));
    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session) fetchAll();
  }, [session]);

  async function fetchAll() {
    setLoadingData(true);
    const [{ data: snapshots }, { data: openTrades }, { data: closedTrades }, { data: signals }, { data: runs }] = await Promise.all([
      supabase.from("account_snapshots").select("*").order("created_at", { ascending: true }).limit(200),
      supabase.from("trades").select("*").is("exit_date", null).order("entry_date", { ascending: false }),
      // Closed trades -- joined client-side against `signals` SELL rows
      // in SignalsFeed to show realized $ P&L per exit. A pyramided
      // stack exits as several trades rows sharing one exit_date (one
      // per unit, see live/run_live.py), so SignalsFeed sums these by
      // (ticker, exit_date) rather than assuming a 1:1 row match.
      supabase.from("trades").select("*").not("exit_date", "is", null).order("exit_date", { ascending: false }).limit(100),
      supabase.from("signals").select("*").order("signal_date", { ascending: false }).limit(15),
      supabase.from("backtest_runs").select("*").order("created_at", { ascending: false }).limit(10),
    ]);
    setData({
      snapshots: snapshots ?? [],
      openTrades: openTrades ?? [],
      closedTrades: closedTrades ?? [],
      signals: signals ?? [],
      runs: runs ?? [],
    });
    setLoadingData(false);
  }

  if (session === undefined) {
    return <div style={{ minHeight: "100vh", background: "var(--bg)" }} />;
  }

  if (!session) {
    return <Login />;
  }

  const latestSnapshot = data.snapshots[data.snapshots.length - 1] ?? null;
  const previousSnapshot = data.snapshots[data.snapshots.length - 2] ?? null;

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <StatusBar
        mode="paper"
        strategyLabel="ma-crossover"
        lastCheck={latestSnapshot?.created_at}
        onSignOut={() => supabase.auth.signOut()}
      />

      <SummaryCards
        latestSnapshot={latestSnapshot}
        previousSnapshot={previousSnapshot}
        openPositionsCount={data.openTrades.length}
      />

      <EquityChart snapshots={data.snapshots} />

      <div style={{ display: "flex", gap: 12, padding: "20px 24px 0 24px", flexWrap: "wrap" }}>
        <PositionsTable openTrades={data.openTrades} accessToken={session.access_token} />
        <SignalsFeed signals={data.signals} closedTrades={data.closedTrades} />
      </div>

      <div style={{ padding: "20px 24px 24px 24px" }}>
        <BacktestComparison runs={data.runs} />
      </div>

      {loadingData && (
        <div style={{ position: "fixed", bottom: 16, right: 16, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-faint)" }}>
          refreshing…
        </div>
      )}
    </div>
  );
}
