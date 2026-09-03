// Vercel serverless function -- proxies a backtest report from Supabase
// Storage, setting Content-Type: text/html explicitly on OUR response
// rather than trusting whatever content-type the report actually got
// served with. Built specifically because linking straight to Storage's
// public URL rendered the report as raw HTML source text instead of a
// rendered page -- object-storage providers commonly apply their own
// content-type handling for user-uploaded files served from a public
// bucket (a defensive measure against stored-XSS-via-upload), which can
// override whatever content-type was set at upload time regardless of
// how storage/supabase_client.py's upload_report() calls it. This
// sidesteps that entirely: whatever Supabase actually serves the file
// as, the browser always gets an explicit text/html Content-Type here.
//
// No auth on this endpoint -- the underlying bucket is already public
// (same reasoning as api/quotes.js being left open: nothing sensitive
// passes through, this just re-serves already-public data with a
// corrected header), so gating the proxy wouldn't add real protection
// anyway (the raw Storage URL is still directly fetchable regardless).
//
// GET /api/report?label=<run_label>

const REPORTS_BUCKET = "backtest-reports";

export default async function handler(req, res) {
  const label = req.query.label;
  if (!label) {
    res.status(400).send("Missing ?label=");
    return;
  }
  const safeLabel = String(Array.isArray(label) ? label[0] : label).replace(/ /g, "_");
  const supabaseUrl = process.env.VITE_SUPABASE_URL;
  if (!supabaseUrl) {
    res.status(500).send("VITE_SUPABASE_URL not configured on the server");
    return;
  }
  const url = `${supabaseUrl}/storage/v1/object/public/${REPORTS_BUCKET}/${encodeURIComponent(safeLabel)}_report.html`;

  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      res.status(resp.status).send(`Report not found (${resp.status}) -- it may not have uploaded successfully, or the "${REPORTS_BUCKET}" bucket isn't set up yet.`);
      return;
    }
    const html = await resp.text();
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.status(200).send(html);
  } catch (e) {
    res.status(500).send(`Failed to load report: ${e}`);
  }
}
