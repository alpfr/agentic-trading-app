import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Shield, ShieldAlert, Activity, PieChart, Info, Database, BarChart3, TrendingUp, TrendingDown, Settings2, Play, PlayCircle, XCircle, Search, Lightbulb, Star } from 'lucide-react';
import { AdvancedRealTimeChart } from "react-ts-tradingview-widgets";
import './index.css';
import './App.css';

// ---------------------------------------------------------------------------
// Config — driven by Vite env vars so this never needs to be hardcoded.
// Set VITE_API_BASE_URL and VITE_API_KEY in your .env / CI pipeline.
// ---------------------------------------------------------------------------
const API_BASE = import.meta.env.VITE_API_BASE_URL || window.location.origin;
const API_KEY  = import.meta.env.VITE_API_KEY       || '';

// Axios instance with auth header on every request
const api = axios.create({
  baseURL: API_BASE,
  headers: { 'X-API-Key': API_KEY },
});

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const setTab = (tab) => { setActiveTab(tab); setMobileMoreOpen(false); };
  const [isLiveMode, _setIsLiveMode] = useState(false);

  // State driven by SSE stream
  const [accountValue, setAccountValue] = useState(0);
  const [positions, setPositions] = useState([]);
  const [watchlist, setWatchlist] = useState(['VTI','SCHD','DGRO','QQQ','JNJ','KO','PG','ABBV','VZ','MSFT','AAPL','NVDA','GOOGL','AMZN']);
  const [rebalanceReport, setRebalanceReport] = useState(null);
  const [dividends, setDividends] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [tradingStyle, setTradingStyle] = useState('retirement');
  const [watchlistData, setWatchlistData] = useState({});
  const [watchlistScanning, setWatchlistScanning] = useState(false);
  const [tradingConfig, setTradingConfig] = useState(null);
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
    const moversInterval = setInterval(fetchMovers, 60000);

    fetchWatchlistConfig();
    watchlist.forEach(t => fetchQuoteForTicker(t));
    fetchRebalance();
    fetchDividends();
    fetchAlerts();
    const rebalInterval = setInterval(fetchRebalance, 300000);  // every 5 min
    const alertInterval = setInterval(fetchAlerts, 120000);     // every 2 min
    const watchlistInterval = setInterval(() => {
      watchlist.forEach(t => fetchQuoteForTicker(t));
    }, 30000);

    return () => {
      sseRef.current?.close();
      clearInterval(marketInterval);
      clearInterval(moversInterval);
      clearInterval(watchlistInterval);
      clearInterval(rebalInterval);
      clearInterval(alertInterval);
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

  async function fetchWatchlistConfig() {
    try {
      const r = await fetch(`${API_BASE}/api/watchlist`, { headers: AUTH_HEADERS });
      if (r.ok) { const d = await r.json(); setTradingConfig(d); setWatchlist(d.watchlist || []); }
    } catch (e) { console.error('Watchlist config fetch failed', e); }
  }

  async function fetchQuoteForTicker(ticker) {
    try {
      const r = await fetch(`${API_BASE}/api/quote/${ticker}`, { headers: AUTH_HEADERS });
      if (r.ok) {
        const d = await r.json();
        setWatchlistData(prev => ({ ...prev, [ticker]: d }));
      }
    } catch (e) {}
  }

  async function scanAllWatchlist() {
    setWatchlistScanning(true);
    try {
      await fetch(`${API_BASE}/api/watchlist/scan`, { method: 'POST', headers: AUTH_HEADERS });
      setTimeout(() => setWatchlistScanning(false), 5000);
    } catch (e) { setWatchlistScanning(false); }
  }

  async function closeAllPositions() {
    if (!window.confirm('Close ALL open positions now?')) return;
    try {
      const r = await fetch(`${API_BASE}/api/watchlist/close-all`, { method: 'POST', headers: AUTH_HEADERS });
      const d = await r.json();
      alert(d.message);
    } catch (e) { alert('Close-all failed: ' + e.message); }
  }

  async function fetchRebalance() {
    try {
      const r = await fetch(`${API_BASE}/api/rebalance`, { headers: AUTH_HEADERS });
      if (r.ok) setRebalanceReport(await r.json());
    } catch (e) { console.error('Rebalance fetch failed', e); }
  }

  async function fetchDividends() {
    try {
      const r = await fetch(`${API_BASE}/api/dividends`, { headers: AUTH_HEADERS });
      if (r.ok) setDividends(await r.json());
    } catch (e) { console.error('Dividends fetch failed', e); }
  }

  async function fetchAlerts() {
    try {
      const r = await fetch(`${API_BASE}/api/alerts`, { headers: AUTH_HEADERS });
      if (r.ok) { const d = await r.json(); setAlerts(d.alerts || []); }
    } catch (e) { console.error('Alerts fetch failed', e); }
  }

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
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', position: 'relative' }}>
      {/* SIDEBAR */}
      <nav className="sidebar-desktop" style={{ width: '260px', background: 'var(--bg-panel)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
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
          <SidebarButton active={activeTab === 'dashboard'}  icon={<PieChart />}    label="Portfolio"       onClick={() => setActiveTab('dashboard')} />
          <SidebarButton active={activeTab === 'watchlist'}  icon={<Star />}        label="Watchlist"       onClick={() => setActiveTab('watchlist')} />
          <SidebarButton active={activeTab === 'rebalance'}  icon={<BarChart3 />}   label="Rebalancing"     onClick={() => setActiveTab('rebalance')} />
          <SidebarButton active={activeTab === 'dividends'}  icon={<TrendingUp />}  label="Dividends"       onClick={() => setActiveTab('dividends')} />
          <SidebarButton active={activeTab === 'alerts'}     icon={<Lightbulb />}   label="Alerts"          onClick={() => { setActiveTab('alerts'); fetchAlerts(); }} />
          <SidebarButton active={activeTab === 'insights'}   icon={<Search />}      label="AI Advisor"      onClick={() => setActiveTab('insights')} />
          <SidebarButton active={activeTab === 'audit'}      icon={<Database />}    label="Audit Log"       onClick={() => setActiveTab('audit')} />
          <SidebarButton active={activeTab === 'quote'}      icon={<Settings2 />}   label="Research"        onClick={() => setActiveTab('quote')} />
        </div>

        <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <a href="/guide.html" target="_blank" rel="noopener"
            style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', borderRadius: '8px', textDecoration: 'none', color: 'var(--text-muted)', fontSize: '13px', transition: 'background 0.15s' }}
            onMouseEnter={e => e.currentTarget.style.background='rgba(255,255,255,0.04)'}
            onMouseLeave={e => e.currentTarget.style.background='transparent'}>
            <span style={{ fontSize: '16px' }}>📖</span> How to Use
          </a>
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
      <main className="main-content" style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-dark)', padding: '32px 48px' }}>
        <header className="animate-fade-in page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '40px' }}>
          <div>
            <h2 style={{ fontSize: '28px', fontWeight: 600 }}>Retirement Portfolio</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '4px' }}>Retirement portfolio advisor — 5–10 year horizon · paper trading.</p>
          </div>
          <div className="page-header-actions" style={{ display: 'flex', gap: '24px' }}>
            <div className="ticker-input-row" style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px' }}>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px' }}>Analyze Ticker</p>
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

        {activeTab === 'watchlist' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 700 }}>⭐ My Watchlist</h2>
                <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                  Retirement portfolio · 5–10 yr horizon · daily AI scan · paper trading
                </p>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button onClick={scanAllWatchlist} disabled={watchlistScanning}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '8px', fontWeight: 600, cursor: watchlistScanning ? 'not-allowed' : 'pointer', opacity: watchlistScanning ? 0.7 : 1 }}>
                  <PlayCircle size={16} /> {watchlistScanning ? 'Scanning...' : 'Scan All Now'}
                </button>
                <button onClick={() => setActiveTab('rebalance')}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px', background: 'rgba(79,70,229,0.1)', color: 'var(--primary)', border: '1px solid var(--primary)', borderRadius: '8px', fontWeight: 600, cursor: 'pointer' }}>
                  <BarChart3 size={16} /> Rebalance
                </button>
              </div>
            </div>

            {/* Ticker cards */}
            <div className="watchlist-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px' }}>
              {watchlist.map(ticker => {
                const d = watchlistData[ticker];
                const price = d?.price || d?.regularMarketPrice || null;
                const changePct = d?.change_pct ?? d?.regularMarketChangePercent ?? null;
                const positive = changePct >= 0;
                const color = changePct === null ? 'var(--text-muted)' : positive ? 'var(--success)' : 'var(--danger)';
                const openPos = positions.find(p => p.ticker === ticker);
                return (
                  <div key={ticker} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {/* Ticker header */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontSize: '22px', fontWeight: 800, letterSpacing: '-0.5px' }}>{ticker}</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>{d?.name || d?.shortName || '—'}</div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '20px', fontWeight: 700, fontFamily: 'monospace' }}>
                          {price ? `$${price.toFixed(2)}` : '—'}
                        </div>
                        {changePct !== null && (
                          <div style={{ color, fontSize: '13px', fontWeight: 600 }}>
                            {positive ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}%
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Metrics row */}
                    {d && (
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
                          {d.volume && <div style={{ color: 'var(--text-muted)' }}>Vol: <span style={{ color: 'var(--text)' }}>{d.volume >= 1e6 ? (d.volume/1e6).toFixed(1)+'M' : d.volume >= 1e3 ? (d.volume/1e3).toFixed(0)+'K' : d.volume}</span></div>}
                        {d.sma_20 && <div style={{ color: 'var(--text-muted)' }}>vs SMA20: <span style={{ color: price > d.sma_20 ? 'var(--success)' : 'var(--danger)' }}>{price > d.sma_20 ? '▲' : '▼'} {price && d.sma_20 ? ((price/d.sma_20 - 1)*100).toFixed(1)+'%' : '—'}</span></div>}
                        {d.sma_50 && <div style={{ color: 'var(--text-muted)' }}>vs SMA200: <span style={{ color: price > d.sma_50 ? 'var(--success)' : 'var(--danger)' }}>{price > d.sma_50 ? '▲' : '▼'} {price && d.sma_50 ? ((price/d.sma_50 - 1)*100).toFixed(1)+'%' : '—'}</span></div>}
                        {d.dividend_yield && <div style={{ color: 'var(--text-muted)' }}>Yield: <span style={{ color: '#fbbf24' }}>{d.dividend_yield?.toFixed(2)}%</span></div>}
                      </div>
                    )}

                    {/* Open position badge */}
                    {openPos && (
                      <div style={{ background: 'rgba(79,70,229,0.1)', border: '1px solid var(--primary)', borderRadius: '8px', padding: '8px 12px', fontSize: '12px' }}>
                        <div style={{ fontWeight: 700, color: 'var(--primary)', marginBottom: '4px' }}>📊 Open Position</div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span>{openPos.shares} shares @ ${openPos.entry?.toFixed(2)}</span>
                          <span style={{ color: (openPos.current - openPos.entry) >= 0 ? 'var(--success)' : 'var(--danger)', fontWeight: 600 }}>
                            {((openPos.current - openPos.entry) / openPos.entry * 100).toFixed(2)}%
                          </span>
                        </div>
                        {openPos.stop && <div style={{ color: 'var(--danger)', marginTop: '2px' }}>Stop: ${openPos.stop?.toFixed(2)}</div>}
                      </div>
                    )}

                    {/* Action buttons */}
                    <div style={{ display: 'flex', gap: '8px', marginTop: 'auto' }}>
                      <button onClick={() => { setQuoteTicker(ticker); setActiveTab('quote'); }}
                        style={{ flex: 1, padding: '7px', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: '6px', fontSize: '12px', cursor: 'pointer' }}>
                        Quote
                      </button>
                      <button onClick={async () => {
                          const r = await fetch(`${API_BASE}/api/trigger`, { method: 'POST', headers: { ...AUTH_HEADERS, 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker }) });
                          const d = await r.json();
                          alert(`${ticker}: ${d.result || d.detail || 'Agent triggered'}`);
                        }}
                        style={{ flex: 2, padding: '7px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}>
                        Run Agent
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Config panel */}
            {tradingConfig && (
              <div style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontWeight: 700, marginBottom: '12px', fontSize: '15px' }}>⚙️ Active Trading Config</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '12px', fontSize: '13px' }}>
                  {[
                    ['Style', tradingConfig.style],
                    ['Horizon', tradingConfig.horizon_years ? tradingConfig.horizon_years + ' years' : '5-10 yr'],
                    ['Risk/Trade', tradingConfig.risk_per_trade_pct?.toFixed(1) + '%'],
                    ['Max Position', tradingConfig.max_single_position_pct ? (tradingConfig.max_single_position_pct*100).toFixed(0) + '%' : '10%'],
                    ['Trailing Stop', tradingConfig.trailing_stop_pct ? (tradingConfig.trailing_stop_pct*100).toFixed(0) + '%' : '15%'],
                    ['Min Hold', tradingConfig.min_hold_days ? tradingConfig.min_hold_days + ' days' : '30 days'],
                    ['Rebalance Drift', tradingConfig.rebalance_drift_trigger ? (tradingConfig.rebalance_drift_trigger*100).toFixed(0) + '%' : '5%'],
                    ['Paper Only', tradingConfig.paper_only !== false ? 'Yes' : 'No'],
                  ].map(([label, val]) => (
                    <div key={label} style={{ background: 'var(--bg)', borderRadius: '8px', padding: '10px 12px' }}>
                      <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginBottom: '2px' }}>{label}</div>
                      <div style={{ fontWeight: 600 }}>{val}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'dashboard' && (
          <div className="animate-fade-in dashboard-grid" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
            <section className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Holdings (Paper)</h3>
              <div className="table-scroll"><table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', minWidth: '500px' }}>
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
              </table></div>
            </section>

            <section className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Shield size={18} /> Risk Guardrails
              </h3>
              <ConstraintRow label="Max Single Position"   value="2%" limit="10%" />
              <ConstraintRow label="Trailing Stop Alert"   value="–" limit="15%" />
              <ConstraintRow label="Min Hold Period"       value="–" limit="30 days" />
              <ConstraintRow label="Min Signal Confidence" value="–" limit="60%" />
              <div style={{ marginTop: '24px', padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', display: 'flex', gap: '12px' }}>
                <Info color="var(--text-muted)" size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5, margin: 0 }}>
                  The AI agent cannot bypass these mathematical limits. Any recommendation that violates concentration, drawdown, or confidence thresholds is automatically blocked. Positions are never auto-closed — this is a buy-and-hold advisor.
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
            <div className="quote-search-row" style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
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
                <div className="quote-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
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
            <div className="movers-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '24px' }}>
              {[['gainers', 'var(--success)', 'Top Gainers'], ['losers', 'var(--danger)', 'Top Losers'], ['actives', 'var(--primary)', 'Most Active']].map(([key, color, title]) => (
                <div key={key}>
                  <h4 style={{ color, fontWeight: 600, marginBottom: '16px' }}>{title}</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {(movers[key] || []).slice(0, 10).map(m => (
                      <div key={m.ticker} onClick={() => { setQuoteTicker(m.ticker); setActiveTab('quote'); }}
                        style={{ background: `${color}11`, border: `1px solid ${color}33`, padding: '12px 16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', cursor: 'pointer' }}>
                        <div>
                          <div><span style={{ fontWeight: 700, marginRight: '8px' }}>{m.ticker}</span><span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{m.name?.substring(0, 20)}</span></div>
                          {m.volume > 0 && <div style={{ fontSize: '11px', color: 'var(--text-dark)', marginTop: '2px' }}>Vol: {m.volume >= 1e6 ? (m.volume/1e6).toFixed(1)+'M' : m.volume >= 1e3 ? (m.volume/1e3).toFixed(0)+'K' : m.volume}</div>}
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>${m.price?.toFixed(2)}</div>
                          <div style={{ color, fontSize: '12px', fontFamily: 'monospace', fontWeight: 600 }}>{m.change_pct >= 0 ? '+' : ''}{m.change_pct?.toFixed(2)}%</div>
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

        {/* ── REBALANCING TAB ─────────────────────────── */}
        {activeTab === 'rebalance' && (
          <div className="animate-fade-in" style={{ padding: '24px', maxWidth: '1100px', margin: '0 auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <div>
                <h2 style={{ fontSize: '22px', fontWeight: 700, marginBottom: '4px' }}>Portfolio Rebalancing</h2>
                <p style={{ color: 'var(--text-dark)', fontSize: '14px' }}>Target allocations vs current holdings — drift threshold: {rebalanceReport?.drift_threshold_pct?.toFixed(0)}%</p>
              </div>
              <button onClick={fetchRebalance} className="btn-primary" style={{ fontSize: '13px', padding: '8px 16px' }}>Refresh</button>
            </div>
            {rebalanceReport ? (
              <>
                <div style={{ padding: '14px 20px', borderRadius: '10px', marginBottom: '24px',
                  background: rebalanceReport.needs_rebalancing ? 'rgba(251,191,36,0.1)' : 'rgba(34,197,94,0.1)',
                  border: `1px solid ${rebalanceReport.needs_rebalancing ? '#fbbf24' : '#22c55e'}` }}>
                  <p style={{ fontWeight: 600, color: rebalanceReport.needs_rebalancing ? '#fbbf24' : '#22c55e' }}>
                    {rebalanceReport.needs_rebalancing ? '⚠️ Rebalancing Recommended' : '✅ Portfolio On Target'}
                  </p>
                  <p style={{ color: 'var(--text-dark)', fontSize: '13px', marginTop: '4px' }}>{rebalanceReport.summary}</p>
                </div>
                {rebalanceReport.buys?.length > 0 && (
                  <div style={{ marginBottom: '24px' }}>
                    <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#22c55e', marginBottom: '12px' }}>📈 Increase Position</h3>
                    <div style={{ display: 'grid', gap: '10px' }}>
                      {rebalanceReport.buys.map(b => (
                        <div key={b.ticker} className="glass-panel" style={{ padding: '14px 18px', display: 'grid', gridTemplateColumns: '80px 1fr 1fr 1fr 100px', alignItems: 'center', gap: '16px' }}>
                          <span style={{ fontWeight: 700, fontSize: '15px' }}>{b.ticker}</span>
                          <span style={{ fontSize: '13px', color: 'var(--text-dark)' }}>Current: <strong style={{ color: 'var(--text)' }}>{b.current_pct.toFixed(1)}%</strong> → Target: <strong style={{ color: '#22c55e' }}>{b.target_pct.toFixed(1)}%</strong></span>
                          <span style={{ fontSize: '13px', color: 'var(--text-dark)' }}>Gap: <strong style={{ color: '#22c55e' }}>${b.gap_value.toLocaleString(undefined, {maximumFractionDigits:0})}</strong></span>
                          <span style={{ fontSize: '13px', color: 'var(--text-dark)' }}>~{b.shares_to_trade} shares @ ${b.current_price}</span>
                          <span style={{ fontSize: '12px', fontWeight: 600, padding: '4px 10px', borderRadius: '6px', background: 'rgba(34,197,94,0.15)', color: '#22c55e', textAlign: 'center' }}>BUY</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {rebalanceReport.sells?.length > 0 && (
                  <div style={{ marginBottom: '24px' }}>
                    <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#ef4444', marginBottom: '12px' }}>📉 Trim Position</h3>
                    <div style={{ display: 'grid', gap: '10px' }}>
                      {rebalanceReport.sells.map(s => (
                        <div key={s.ticker} className="glass-panel" style={{ padding: '14px 18px', display: 'grid', gridTemplateColumns: '80px 1fr 1fr 1fr 100px', alignItems: 'center', gap: '16px' }}>
                          <span style={{ fontWeight: 700, fontSize: '15px' }}>{s.ticker}</span>
                          <span style={{ fontSize: '13px', color: 'var(--text-dark)' }}>Current: <strong style={{ color: '#ef4444' }}>{s.current_pct.toFixed(1)}%</strong> → Target: <strong>{s.target_pct.toFixed(1)}%</strong></span>
                          <span style={{ fontSize: '13px', color: 'var(--text-dark)' }}>Excess: <strong style={{ color: '#ef4444' }}>${Math.abs(s.gap_value).toLocaleString(undefined, {maximumFractionDigits:0})}</strong></span>
                          <span style={{ fontSize: '13px', color: 'var(--text-dark)' }}>~{s.shares_to_trade} shares @ ${s.current_price}</span>
                          <span style={{ fontSize: '12px', fontWeight: 600, padding: '4px 10px', borderRadius: '6px', background: 'rgba(239,68,68,0.15)', color: '#ef4444', textAlign: 'center' }}>TRIM</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {rebalanceReport.holds?.length > 0 && (
                  <div>
                    <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-dark)', marginBottom: '12px' }}>✓ On Target</h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {rebalanceReport.holds.map(h => (
                        <span key={h.ticker} style={{ padding: '6px 14px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', fontSize: '13px' }}>
                          {h.ticker} <span style={{ color: 'var(--text-dark)' }}>{h.current_pct.toFixed(1)}%</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-dark)' }}>Loading rebalance report...</div>
            )}
          </div>
        )}

        {/* ── DIVIDENDS TAB ───────────────────────────── */}
        {activeTab === 'dividends' && (
          <div className="animate-fade-in" style={{ padding: '24px', maxWidth: '900px', margin: '0 auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <div>
                <h2 style={{ fontSize: '22px', fontWeight: 700, marginBottom: '4px' }}>Dividend Income</h2>
                <p style={{ color: 'var(--text-dark)', fontSize: '14px' }}>Projected income from current paper holdings</p>
              </div>
              {dividends && (
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '28px', fontWeight: 700, color: '#22c55e' }}>${dividends.total_annual_income?.toLocaleString(undefined, {minimumFractionDigits:2})}</div>
                  <div style={{ fontSize: '13px', color: 'var(--text-dark)' }}>est. annual · ${dividends.total_monthly_income?.toFixed(2)}/mo</div>
                </div>
              )}
            </div>
            {dividends?.dividends?.length > 0 ? (
              <div style={{ display: 'grid', gap: '10px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '80px 80px 80px 80px 90px 100px 100px', gap: '16px', padding: '8px 20px', fontSize: '11px', fontWeight: 600, color: 'var(--text-dark)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <span>Ticker</span><span>Yield</span><span>Per Share</span><span>Payout</span><span>Shares</span><span>Annual</span><span>Health</span>
                </div>
                {dividends.dividends.map(d => (
                  <div key={d.ticker} className="glass-panel" style={{ padding: '14px 20px', display: 'grid', gridTemplateColumns: '80px 80px 80px 80px 90px 100px 100px', alignItems: 'center', gap: '16px' }}>
                    <span style={{ fontWeight: 700, fontSize: '15px' }}>{d.ticker}</span>
                    <span style={{ fontWeight: 600, color: '#22c55e' }}>{d.yield_pct.toFixed(2)}%</span>
                    <span>${d.annual_div_rate.toFixed(2)}</span>
                    <span style={{ color: d.payout_ratio > 85 ? '#ef4444' : d.payout_ratio > 65 ? '#fbbf24' : 'var(--text)' }}>{d.payout_ratio.toFixed(0)}%</span>
                    <span>{d.shares_held}</span>
                    <span style={{ color: '#22c55e', fontWeight: 600 }}>${d.annual_income.toFixed(2)}</span>
                    <span style={{ fontSize: '11px', fontWeight: 700, padding: '3px 8px', borderRadius: '5px', textAlign: 'center',
                      color: d.div_health === 'AT_RISK' ? '#ef4444' : d.div_health === 'WATCH' ? '#fbbf24' : d.div_health === 'HEALTHY' ? '#22c55e' : 'var(--text-dark)',
                      background: d.div_health === 'AT_RISK' ? 'rgba(239,68,68,0.12)' : d.div_health === 'WATCH' ? 'rgba(251,191,36,0.12)' : d.div_health === 'HEALTHY' ? 'rgba(34,197,94,0.12)' : 'rgba(255,255,255,0.05)',
                    }}>{d.div_health}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-dark)' }}>
                {dividends ? 'No dividend data yet — scans populate this after market open.' : 'Loading...'}
              </div>
            )}
          </div>
        )}

        {/* ── ALERTS TAB ──────────────────────────────── */}
        {activeTab === 'alerts' && (
          <div className="animate-fade-in" style={{ padding: '24px', maxWidth: '900px', margin: '0 auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <div>
                <h2 style={{ fontSize: '22px', fontWeight: 700, marginBottom: '4px' }}>Portfolio Alerts</h2>
                <p style={{ color: 'var(--text-dark)', fontSize: '14px' }}>Price drops, dividend risks, rebalancing triggers, valuation warnings</p>
              </div>
              <button onClick={fetchAlerts} className="btn-primary" style={{ fontSize: '13px', padding: '8px 16px' }}>Refresh</button>
            </div>
            {alerts.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-dark)' }}>
                <div style={{ fontSize: '40px', marginBottom: '12px' }}>✅</div>
                <p style={{ fontWeight: 600 }}>No active alerts</p>
                <p style={{ fontSize: '13px', marginTop: '8px' }}>Alerts generate after daily agent scans. Check back after market open.</p>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: '12px' }}>
                {alerts.map((a, i) => (
                  <div key={i} className="glass-panel" style={{ padding: '16px 20px', borderLeft: `4px solid ${a.level === 'ACTION' ? '#22c55e' : a.level === 'WARNING' ? '#fbbf24' : '#64748b'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                          <span style={{ fontWeight: 700, fontSize: '15px' }}>{a.ticker}</span>
                          <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px',
                            color: a.level === 'ACTION' ? '#22c55e' : a.level === 'WARNING' ? '#fbbf24' : 'var(--text-dark)',
                            background: a.level === 'ACTION' ? 'rgba(34,197,94,0.12)' : a.level === 'WARNING' ? 'rgba(251,191,36,0.12)' : 'rgba(255,255,255,0.05)',
                          }}>{a.level}</span>
                          <span style={{ fontSize: '11px', color: 'var(--text-dark)' }}>{a.category?.replace('_', ' ')}</span>
                        </div>
                        <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '6px' }}>{a.title}</div>
                        <div style={{ fontSize: '13px', color: 'var(--text-dark)', lineHeight: 1.6 }}>{a.message}</div>
                      </div>
                      <span style={{ fontSize: '11px', fontWeight: 700, padding: '6px 12px', borderRadius: '6px', whiteSpace: 'nowrap',
                        color: a.suggested_action === 'BUY_OPPORTUNITY' ? '#22c55e' : a.suggested_action === 'TRIM' ? '#ef4444' : '#fbbf24',
                        background: a.suggested_action === 'BUY_OPPORTUNITY' ? 'rgba(34,197,94,0.12)' : a.suggested_action === 'TRIM' ? 'rgba(239,68,68,0.12)' : 'rgba(251,191,36,0.12)',
                      }}>{a.suggested_action?.replace(/_/g, ' ')}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <footer style={{ marginTop: '48px', padding: '24px', borderTop: '1px solid var(--border)', textAlign: 'center' }}>
          <p style={{ fontSize: '12px', color: 'var(--text-dark)', maxWidth: '800px', margin: '0 auto', lineHeight: 1.6 }}>
            RETIREMENT RESEARCH TOOL — NOT FINANCIAL ADVICE. Keep actual retirement savings in a tax-advantaged account (401k/IRA/Roth IRA). This tool is for research and paper trading only.
          </p>
        </footer>
      </main>
    
      {/* ── MOBILE BOTTOM NAV ─────────────────────────────────────────── */}
      <nav className="mobile-nav">
        <button className={`mobile-nav-btn ${activeTab === 'dashboard' ? 'active' : ''}`} onClick={() => setTab('dashboard')}>
          <PieChart size={20} /><span>Portfolio</span>
        </button>
        <button className={`mobile-nav-btn ${activeTab === 'watchlist' ? 'active' : ''}`} onClick={() => setTab('watchlist')}>
          <Star size={20} /><span>Watchlist</span>
        </button>
        <button className={`mobile-nav-btn ${activeTab === 'rebalance' ? 'active' : ''}`} onClick={() => setTab('rebalance')}>
          <BarChart3 size={20} /><span>Rebalance</span>
        </button>
        <button className={`mobile-nav-btn ${activeTab === 'alerts' ? 'active' : ''}`} onClick={() => { setTab('alerts'); fetchAlerts(); }}>
          <Lightbulb size={20} /><span>Alerts</span>
        </button>
        <button className={`mobile-nav-btn ${mobileMoreOpen ? 'active' : ''}`} onClick={() => setMobileMoreOpen(o => !o)}>
          <Settings2 size={20} /><span>More</span>
        </button>
      </nav>

      {/* ── MOBILE MORE MENU ──────────────────────────────────────────── */}
      <div className={`mobile-more-menu ${mobileMoreOpen ? 'open' : ''}`}>
        <button className={`mobile-nav-btn ${activeTab === 'dividends' ? 'active' : ''}`} style={{ flexDirection: 'row', justifyContent: 'flex-start', gap: '12px', padding: '12px 16px', fontSize: '14px' }} onClick={() => setTab('dividends')}>
          <TrendingUp size={18} /><span>Dividends</span>
        </button>
        <button className={`mobile-nav-btn ${activeTab === 'insights' ? 'active' : ''}`} style={{ flexDirection: 'row', justifyContent: 'flex-start', gap: '12px', padding: '12px 16px', fontSize: '14px' }} onClick={() => setTab('insights')}>
          <Search size={18} /><span>AI Advisor</span>
        </button>
        <button className={`mobile-nav-btn ${activeTab === 'quote' ? 'active' : ''}`} style={{ flexDirection: 'row', justifyContent: 'flex-start', gap: '12px', padding: '12px 16px', fontSize: '14px' }} onClick={() => setTab('quote')}>
          <Settings2 size={18} /><span>Research</span>
        </button>
        <button className={`mobile-nav-btn ${activeTab === 'audit' ? 'active' : ''}`} style={{ flexDirection: 'row', justifyContent: 'flex-start', gap: '12px', padding: '12px 16px', fontSize: '14px' }} onClick={() => setTab('audit')}>
          <Database size={18} /><span>Audit Log</span>
        </button>
      </div>

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
