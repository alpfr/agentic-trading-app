import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Shield, ShieldAlert, Activity, PieChart, Info, Database, BarChart3, TrendingUp, Settings2, Play, Search, Lightbulb } from 'lucide-react';
import { AdvancedRealTimeChart } from "react-ts-tradingview-widgets";
import './index.css';

// ---------------------------------------------------------------------------
// Config — driven by Vite env vars so this never needs to be hardcoded.
// Set VITE_API_BASE_URL and VITE_API_KEY in your .env / CI pipeline.
// ---------------------------------------------------------------------------
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const API_KEY  = import.meta.env.VITE_API_KEY       || '';

// Axios instance with auth header on every request
const api = axios.create({
  baseURL: API_BASE,
  headers: { 'X-API-Key': API_KEY },
});

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isLiveMode, _setIsLiveMode] = useState(false);

  // State driven by SSE stream
  const [accountValue, setAccountValue] = useState(0);
  const [positions, setPositions] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [agentInsights, setAgentInsights] = useState([]);
  const [connected, setConnected] = useState(false);

  // Market data history (still polled separately — low frequency)
  const [marketDataHistory, setMarketDataHistory] = useState([]);

  const [targetTicker, setTargetTicker] = useState('AAPL');
  const [isSimulating, setIsSimulating] = useState(false);

  const [quoteTicker, setQuoteTicker] = useState('TSLA');
  const [quoteData, setQuoteData] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(false);

  const [movers, setMovers] = useState({ gainers: [], losers: [], actives: [] });
  const [moversLoading, setMoversLoading] = useState(false);

  const sseRef = useRef(null);

  // -------------------------------------------------------------------------
  // SSE — replaces the 2-second polling loop that fired 4 requests per cycle
  // -------------------------------------------------------------------------
  useEffect(() => {
    const connectSSE = () => {
      // EventSource doesn't support custom headers natively.
      // We append the API key as a query param for the SSE endpoint.
      const url = `${API_BASE}/api/stream?api_key=${encodeURIComponent(API_KEY)}`;
      const es = new EventSource(url);
      sseRef.current = es;

      es.onopen = () => setConnected(true);

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.error) { console.error('SSE error payload:', data.error); return; }
          if (data.logs)      setAuditLogs(data.logs);
          if (data.insights)  setAgentInsights(data.insights);
          if (data.positions)  setPositions(data.positions);
          if (data.account_value) setAccountValue(data.account_value);
        } catch (e) {
          console.error('Failed to parse SSE payload', e);
        }
      };

      es.onerror = () => {
        setConnected(false);
        es.close();
        // Reconnect after 5s
        setTimeout(connectSSE, 5000);
      };
    };

    connectSSE();

    // Market data history — lower frequency, still polled
    const fetchMarketHistory = async () => {
      try {
        const res = await api.get('/api/market-data');
        setMarketDataHistory(res.data.saved_data || []);
      } catch { /* silent */ }
    };
    fetchMarketHistory();
    const marketInterval = setInterval(fetchMarketHistory, 30000);

    // Movers — low frequency
    fetchMovers();
    const moversInterval = setInterval(fetchMovers, 30000);

    return () => {
      sseRef.current?.close();
      clearInterval(marketInterval);
      clearInterval(moversInterval);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------
  const lookupQuote = async () => {
    setQuoteLoading(true);
    try {
      const res = await api.get(`/api/quote/${quoteTicker}`);
      setQuoteData(res.data);
    } catch { alert('Failed to fetch quote.'); }
    setQuoteLoading(false);
  };

  async function fetchMovers() {
    setMoversLoading(true);
    try {
      const res = await api.get('/api/movers');
      setMovers(res.data);
    } catch { console.error('Failed to fetch movers.'); }
    setMoversLoading(false);
  }

  const triggerAgent = async () => {
    setIsSimulating(true);
    try {
      await api.post('/api/trigger', { ticker: targetTicker });
    } catch (err) {
      const detail = err.response?.data?.detail || err.message;
      alert(`Trigger failed: ${detail}`);
    }
    setTimeout(() => setIsSimulating(false), 1500);
  };

  const clearMarketDatabase = async () => {
    if (!window.confirm('Delete all saved market data records?')) return;
    try {
      await api.delete('/api/market-data');
      setMarketDataHistory([]);
    } catch { alert('Failed to clear database.'); }
  };

  // PnL computed client-side from SSE positions
  const _totalPnlDollars = positions.reduce((sum, p) => {
    if (!p.entry || !p.current) return sum;
    const raw = (p.current - p.entry) * p.shares;
    return sum + (p.side === 'SHORT' ? -raw : raw);
  }, 0);

  const positionsWithPnl = positions.map(p => {
    if (!p.entry || p.entry === 0) return { ...p, pnl_pct: 0 };
    const pnl_pct = ((p.current - p.entry) / p.entry) * 100 * (p.side === 'SHORT' ? -1 : 1);
    return { ...p, pnl_pct: Math.round(pnl_pct * 10000) / 10000 };
  });

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* SIDEBAR */}
      <nav style={{ width: '260px', background: 'var(--bg-panel)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '24px', borderBottom: '1px solid var(--border)' }}>
          <h1 style={{ fontSize: '20px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity color="var(--primary)" size={24} />
            <span className="text-gradient">AgenticTrade.ai</span>
          </h1>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px', letterSpacing: '0.05em' }}>v1.1.0</p>
          {/* SSE Connection Indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '8px' }}>
            <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: connected ? 'var(--success)' : 'var(--danger)' }} />
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{connected ? 'Live stream active' : 'Reconnecting...'}</span>
          </div>
        </div>

        <div style={{ flex: 1, padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <SidebarButton active={activeTab === 'dashboard'} icon={<PieChart />} label="Portfolio & Risk" onClick={() => setActiveTab('dashboard')} />
          <SidebarButton active={activeTab === 'insights'}  icon={<Lightbulb />} label="AI Insights"      onClick={() => setActiveTab('insights')} />
          <SidebarButton active={activeTab === 'movers'}    icon={<TrendingUp />} label="Market Movers"    onClick={() => setActiveTab('movers')} />
          <SidebarButton active={activeTab === 'quote'}     icon={<Search />}    label="Quote Lookup"     onClick={() => setActiveTab('quote')} />
          <SidebarButton active={activeTab === 'audit'}     icon={<Database />}  label="Audit Journal"    onClick={() => setActiveTab('audit')} />
          <SidebarButton active={activeTab === 'market'}    icon={<BarChart3 />} label="Market History DB" onClick={() => setActiveTab('market')} />
          <SidebarButton active={activeTab === 'settings'}  icon={<Settings2 />} label="Constraints"      onClick={() => setActiveTab('settings')} />
        </div>

        <div style={{ padding: '24px', borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.01)' }}>
          <div style={{ padding: '12px', background: isLiveMode ? 'var(--danger-bg)' : 'rgba(79, 70, 229, 0.1)', border: `1px solid ${isLiveMode ? 'var(--danger)' : 'var(--primary)'}`, borderRadius: '12px', display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
            {isLiveMode ? <ShieldAlert color="var(--danger)" size={20} style={{ flexShrink: 0 }} /> : <Shield color="var(--primary)" size={20} style={{ flexShrink: 0 }} />}
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: isLiveMode ? 'var(--danger)' : 'var(--primary)' }}>
                {isLiveMode ? 'LIVE TRADING MODE' : 'PAPER TRADING ONLY'}
              </p>
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', lineHeight: 1.4 }}>
                {isLiveMode ? 'Routing to broker APIs.' : 'Execution layer is simulated.'}
              </p>
              {!isLiveMode && (
                <button onClick={() => alert('SECURITY GATE: Live Mode requires explicit CLI configuration toggle.')} style={{ marginTop: '8px', padding: '4px 8px', background: 'transparent', border: '1px solid var(--primary)', color: 'var(--primary)', borderRadius: '4px', fontSize: '10px', fontWeight: 600 }}>UNLOCK LIVE</button>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* MAIN CONTENT */}
      <main style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-dark)', padding: '32px 48px' }}>
        <header className="animate-fade-in" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '40px' }}>
          <div>
            <h2 style={{ fontSize: '28px', fontWeight: 600 }}>Portfolio Command Center</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '4px' }}>Deterministic risk enforcement active.</p>
          </div>
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px' }}>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px' }}>Trigger Autonomous Agents</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input type="text" value={targetTicker} onChange={(e) => setTargetTicker(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))}
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', color: '#fff', padding: '8px 12px', borderRadius: '6px', width: '80px', fontFamily: 'monospace' }} />
                <button onClick={triggerAgent} disabled={isSimulating}
                  style={{ background: 'var(--primary)', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '6px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px', opacity: isSimulating ? 0.7 : 1, cursor: 'pointer' }}>
                  {isSimulating ? <Activity size={16} /> : <Play size={16} />}
                  {isSimulating ? 'Processing...' : 'Run Cycle'}
                </button>
              </div>
            </div>
            <StatCard label="Total Equity" value={accountValue ? `$${accountValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '--'} />
            <div style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '4px' }}>Risk Engine</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--success)' }} />
                <span style={{ fontSize: '15px', fontWeight: 500, color: 'var(--success)' }}>ONLINE</span>
              </div>
            </div>
          </div>
        </header>

        {activeTab === 'dashboard' && (
          <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
            <section className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Active Paper Positions</h3>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ color: 'var(--text-dark)', fontSize: '12px', textTransform: 'uppercase' }}>
                    <th style={{ paddingBottom: '12px' }}>Asset</th><th style={{ paddingBottom: '12px' }}>Side</th>
                    <th style={{ paddingBottom: '12px' }}>Shares</th><th style={{ paddingBottom: '12px' }}>Entry</th>
                    <th style={{ paddingBottom: '12px' }}>Current</th><th style={{ paddingBottom: '12px' }}>Stop</th>
                    <th style={{ paddingBottom: '12px', textAlign: 'right' }}>PNL %</th>
                  </tr>
                </thead>
                <tbody>
                  {positionsWithPnl.length === 0 && (
                    <tr><td colSpan="7" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)' }}>No active positions. Run an agent cycle.</td></tr>
                  )}
                  {positionsWithPnl.map(pos => (
                    <tr key={pos.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '16px 0', fontWeight: 600 }}>{pos.ticker}</td>
                      <td style={{ padding: '16px 0' }}><span style={{ background: 'rgba(52,211,153,0.1)', color: '#34D399', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600 }}>{pos.side}</span></td>
                      <td style={{ padding: '16px 0', color: 'var(--text-muted)' }}>{pos.shares}</td>
                      <td style={{ padding: '16px 0', fontFamily: 'monospace' }}>${pos.entry?.toFixed(2)}</td>
                      <td style={{ padding: '16px 0', fontFamily: 'monospace' }}>${pos.current?.toFixed(2)}</td>
                      <td style={{ padding: '16px 0', fontFamily: 'monospace', color: 'var(--warning)' }}>${pos.stop?.toFixed(2)}</td>
                      <td style={{ padding: '16px 0', textAlign: 'right', fontWeight: 600, color: pos.pnl_pct >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                        {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct?.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Activity size={18} /> Deterministic Constraints
              </h3>
              <ConstraintRow label="Max Daily Loss"        value="3.0%" limit="3.0%" />
              <ConstraintRow label="Account Exposure"      value="8.4%" limit="100.0%" />
              <ConstraintRow label="Sector Correlation"    value="12%"  limit="20%" />
              <div style={{ marginTop: '24px', padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', display: 'flex', gap: '12px' }}>
                <Info color="var(--text-muted)" size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5, margin: 0 }}>
                  The Multi-Agent system cannot bypass these mathematical boundaries. Any LLM-proposed trade exceeding these configurations is instantly rejected by the Python execution layer.
                </p>
              </div>
            </section>
          </div>
        )}

        {activeTab === 'insights' && (
          <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>Agent Execution Insights</h3>
            {agentInsights.length === 0 && <p style={{ color: 'var(--text-muted)' }}>No AI insights yet. Run an agent cycle.</p>}
            {agentInsights.map(insight => (
              <div key={insight.id} className="glass-panel" style={{ padding: '24px', position: 'relative', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '4px', background: insight.action === 'BUY' ? 'var(--success)' : insight.action === 'SELL' ? 'var(--danger)' : 'var(--warning)' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                      <h4 style={{ fontSize: '24px', fontWeight: 700, margin: 0 }}>{insight.ticker}</h4>
                      <span style={{ padding: '4px 10px', borderRadius: '4px', fontSize: '12px', fontWeight: 700, background: insight.action === 'BUY' ? 'rgba(52,211,153,0.1)' : insight.action === 'SELL' ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)', color: insight.action === 'BUY' ? 'var(--success)' : insight.action === 'SELL' ? 'var(--danger)' : 'var(--warning)' }}>{insight.action}</span>
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{insight.time}</span>
                    </div>
                    <p style={{ margin: 0, fontSize: '15px', lineHeight: 1.6, color: 'var(--text-dark)', maxWidth: '90%' }}><strong>AI Rationale:</strong> {insight.rationale}</p>
                  </div>
                  <div style={{ textAlign: 'right', background: 'rgba(255,255,255,0.03)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                    <p style={{ margin: 0, fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>Confidence</p>
                    <p style={{ margin: 0, fontSize: '20px', fontWeight: 600, fontFamily: 'monospace', color: insight.confidence >= 0.7 ? 'var(--success)' : insight.confidence <= 0.3 ? 'var(--danger)' : 'var(--warning)' }}>{(insight.confidence * 100).toFixed(0)}%</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Immutable Execution Journal</h3>
            {auditLogs.length === 0 && <p style={{ color: 'var(--text-muted)' }}>No events yet.</p>}
            {auditLogs.map(log => (
              <div key={log.id} style={{ display: 'flex', gap: '24px', padding: '16px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ color: 'var(--text-dark)', fontFamily: 'monospace', fontSize: '13px' }}>{log.time}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <span style={{ fontWeight: 600 }}>{log.agent}</span>
                    <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 6px', borderRadius: '4px', background: log.action === 'REJECTED' ? 'var(--danger-bg)' : log.action === 'FILLED' ? 'var(--success-bg)' : 'rgba(255,255,255,0.1)', color: log.action === 'REJECTED' ? 'var(--danger)' : log.action === 'FILLED' ? 'var(--success)' : '#fff' }}>{log.action}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>[{log.ticker}]</span>
                  </div>
                  <p style={{ fontSize: '14px', color: 'var(--text-muted)', margin: 0 }}>{log.reason}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'market' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, margin: 0 }}>Database: Real-Time Price Storage</h3>
              <button onClick={clearMarketDatabase} style={{ background: 'transparent', color: 'var(--danger)', border: '1px solid var(--danger)', padding: '6px 12px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer' }}>Clear Database</button>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead><tr style={{ color: 'var(--text-dark)', fontSize: '12px', textTransform: 'uppercase' }}>
                <th style={{ paddingBottom: '12px' }}>ID</th><th style={{ paddingBottom: '12px' }}>Timestamp</th>
                <th style={{ paddingBottom: '12px' }}>Ticker</th><th style={{ paddingBottom: '12px' }}>Price</th><th style={{ paddingBottom: '12px' }}>VIX</th>
              </tr></thead>
              <tbody>
                {marketDataHistory.length === 0 && <tr><td colSpan="5" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)' }}>No records yet. Run a cycle.</td></tr>}
                {marketDataHistory.map(row => (
                  <tr key={row.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '16px 0', color: 'var(--text-muted)' }}>#{row.id}</td>
                    <td style={{ padding: '16px 0', fontFamily: 'monospace', fontSize: '12px', color: 'var(--text-muted)' }}>{new Date(row.timestamp).toLocaleString()}</td>
                    <td style={{ padding: '16px 0', fontWeight: 600 }}>{row.ticker}</td>
                    <td style={{ padding: '16px 0', fontFamily: 'monospace' }}>${parseFloat(row.price).toFixed(2)}</td>
                    <td style={{ padding: '16px 0', fontFamily: 'monospace' }}>{parseFloat(row.vix).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'quote' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Stock Quote & Research</h3>
            <div style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
              <input type="text" value={quoteTicker} onChange={(e) => setQuoteTicker(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))}
                placeholder="Ticker (e.g. AAPL)" onKeyDown={(e) => e.key === 'Enter' && lookupQuote()}
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', color: '#fff', padding: '10px 16px', borderRadius: '8px', flex: 1, maxWidth: '250px', outline: 'none' }} />
              <button onClick={lookupQuote} disabled={quoteLoading}
                style={{ background: 'var(--primary)', color: '#fff', border: 'none', padding: '10px 24px', borderRadius: '8px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', opacity: quoteLoading ? 0.7 : 1 }}>
                {quoteLoading ? <Activity size={18} /> : <Search size={18} />} {quoteLoading ? 'Searching...' : 'Lookup'}
              </button>
            </div>
            {quoteData && (
              <div className="animate-fade-in" style={{ background: 'rgba(255,255,255,0.02)', padding: '24px', borderRadius: '12px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
                  <div>
                    <h2 style={{ fontSize: '28px', fontWeight: 700, margin: '0 0 4px 0' }}>{quoteData.ticker} <span style={{ fontSize: '18px', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '8px' }}>{quoteData.name}</span></h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>{quoteData.sector} • {quoteData.industry}</p>
                  </div>
                  <h2 style={{ fontSize: '32px', fontWeight: 600, margin: 0 }}>${quoteData.current_price?.toFixed(2) || 'N/A'}</h2>
                </div>
                <div style={{ height: '400px', marginBottom: '24px', borderRadius: '12px', overflow: 'hidden' }}>
                  <AdvancedRealTimeChart theme="dark" symbol={quoteData.ticker} width="100%" height="100%" allow_symbol_change={false} />
                </div>
                <p style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--text-dark)', margin: 0 }}>{quoteData.summary}</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'movers' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, margin: 0 }}>Top Gainers &amp; Losers</h3>
              <button onClick={fetchMovers} disabled={moversLoading} style={{ background: 'transparent', color: 'var(--primary)', border: '1px solid var(--primary)', padding: '6px 12px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', opacity: moversLoading ? 0.7 : 1 }}>
                {moversLoading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '24px' }}>
              {[['gainers', 'var(--success)', 'Top Gainers'], ['losers', 'var(--danger)', 'Top Losers'], ['actives', 'var(--primary)', 'Most Active']].map(([key, color, title]) => (
                <div key={key}>
                  <h4 style={{ color, fontWeight: 600, marginBottom: '16px' }}>{title}</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {(movers[key] || []).slice(0, 10).map(m => (
                      <div key={m.ticker} onClick={() => { setQuoteTicker(m.ticker); setActiveTab('quote'); }}
                        style={{ background: `${color}11`, border: `1px solid ${color}33`, padding: '12px 16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', cursor: 'pointer' }}>
                        <div><span style={{ fontWeight: 700, marginRight: '8px' }}>{m.ticker}</span><span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{m.name?.substring(0, 20)}</span></div>
                        <div style={{ textAlign: 'right' }}>
                          <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>${m.price?.toFixed(2)}</div>
                          <div style={{ color, fontSize: '12px', fontFamily: 'monospace' }}>{m.change_pct >= 0 ? '+' : ''}{m.change_pct?.toFixed(2)}%</div>
                        </div>
                      </div>
                    ))}
                    {!(movers[key]?.length) && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>No data.</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <footer style={{ marginTop: '48px', padding: '24px', borderTop: '1px solid var(--border)', textAlign: 'center' }}>
          <p style={{ fontSize: '12px', color: 'var(--text-dark)', maxWidth: '800px', margin: '0 auto', lineHeight: 1.6 }}>
            NOT FINANCIAL ADVICE. Do not use with real capital without extensive professional review.
          </p>
        </footer>
      </main>
    </div>
  );
}

function SidebarButton({ icon, label, active, onClick }) {
  return (
    <button onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 16px', width: '100%', background: active ? 'rgba(255,255,255,0.03)' : 'transparent', border: 'none', borderRadius: '8px', color: active ? '#fff' : 'var(--text-muted)', fontWeight: active ? 500 : 400, borderRight: active ? '3px solid var(--primary)' : '3px solid transparent', cursor: 'pointer' }}>
      {React.cloneElement(icon, { size: 18, color: active ? 'var(--primary)' : 'currentColor' })}
      <span>{label}</span>
    </button>
  );
}

function StatCard({ label, value }) {
  return (
    <div style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px', minWidth: '160px' }}>
      <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px' }}>{label}</p>
      <h3 style={{ fontSize: '24px', fontWeight: 600, fontFamily: 'monospace', margin: 0 }}>{value}</h3>
    </div>
  );
}

function ConstraintRow({ label, value, limit }) {
  const isHealthy = parseFloat(value) < (parseFloat(limit) * 0.8);
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
      <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ fontSize: '14px', fontWeight: 600, color: isHealthy ? 'var(--success)' : 'var(--warning)', fontFamily: 'monospace' }}>{value}</span>
        <span style={{ fontSize: '12px', color: 'var(--text-dark)', fontFamily: 'monospace' }}>/ {limit}</span>
      </div>
    </div>
  );
}
