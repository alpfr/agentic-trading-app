import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Shield, ShieldAlert, Activity, PieChart, Info, Database, BarChart3, TrendingUp, Settings2, Play, Search } from 'lucide-react';
import './index.css';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isLiveMode, setIsLiveMode] = useState(false);

  // Real-time states
  const [accountValue, setAccountValue] = useState(105240.50);
  const [positions, setPositions] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [marketDataHistory, setMarketDataHistory] = useState([]);
  const [targetTicker, setTargetTicker] = useState('AAPL');
  const [isSimulating, setIsSimulating] = useState(false);

  // Quote states
  const [quoteTicker, setQuoteTicker] = useState('TSLA');
  const [quoteData, setQuoteData] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(false);

  // Movers states
  const [movers, setMovers] = useState({ gainers: [], losers: [], actives: [] });
  const [moversLoading, setMoversLoading] = useState(false);

  const lookupQuote = async () => {
    setQuoteLoading(true);
    try {
      const res = await axios.get(`http://localhost:8002/api/quote/${quoteTicker}`);
      setQuoteData(res.data);
    } catch (err) {
      alert("Failed to fetch quote.");
    }
    setQuoteLoading(false);
  };

  const fetchMovers = async () => {
    setMoversLoading(true);
    try {
      const res = await axios.get('http://localhost:8002/api/movers');
      setMovers(res.data);
    } catch (err) {
      console.error("Failed to fetch movers.");
    }
    setMoversLoading(false);
  };

  // Poll FastAPI Backend
  useEffect(() => {
    const fetchStates = async () => {
      try {
        const portRes = await axios.get('http://localhost:8002/api/portfolio');
        setPositions(portRes.data.positions);
        if (portRes.data.account_value) {
          setAccountValue(portRes.data.account_value);
        }

        const logRes = await axios.get('http://localhost:8002/api/logs');
        setAuditLogs(logRes.data.logs);

        // Fetch market data history from our DB
        const marketRes = await axios.get('http://localhost:8002/api/market-data');
        setMarketDataHistory(marketRes.data.saved_data || []);
      } catch (err) {
        console.error("Backend Disconnected:", err);
      }
    };

    // Initial fetch, then poll states every 2 seconds
    fetchStates();
    const stateInterval = setInterval(fetchStates, 2000);

    // Poll Yahoo Finance for trending movers every 15 seconds
    fetchMovers();
    const moversInterval = setInterval(fetchMovers, 15000);

    return () => {
      clearInterval(stateInterval);
      clearInterval(moversInterval);
    };
  }, []);

  const triggerAgent = async () => {
    setIsSimulating(true);
    try {
      await axios.post('http://localhost:8002/api/trigger', { ticker: targetTicker });
    } catch (err) {
      alert("FastAPI backend is not running. Start with 'uvicorn app:app --reload' in the backend directory.");
    }
    setTimeout(() => setIsSimulating(false), 1500);
  };

  const clearMarketDatabase = async () => {
    if (!window.confirm("Are you sure you want to delete all saved market data records?")) return;
    try {
      await axios.delete('http://localhost:8002/api/market-data');
    } catch (err) {
      alert("Failed to clear database.");
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* SIDEBAR */}
      <nav style={{ width: '260px', background: 'var(--bg-panel)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '24px', borderBottom: '1px solid var(--border)' }}>
          <h1 style={{ fontSize: '20px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity color="var(--primary)" size={24} />
            <span className="text-gradient">AgenticTrade.ai</span>
          </h1>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px', letterSpacing: '0.05em' }}>v1.0.0-beta</p>
        </div>

        <div style={{ flex: 1, padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <SidebarButton active={activeTab === 'dashboard'} icon={<PieChart />} label="Portfolio & Risk" onClick={() => setActiveTab('dashboard')} />
          <SidebarButton active={activeTab === 'movers'} icon={<TrendingUp />} label="Market Movers" onClick={() => setActiveTab('movers')} />
          <SidebarButton active={activeTab === 'quote'} icon={<Search />} label="Quote Lookup" onClick={() => setActiveTab('quote')} />
          <SidebarButton active={activeTab === 'audit'} icon={<Database />} label="Audit Journal" onClick={() => setActiveTab('audit')} />
          <SidebarButton active={activeTab === 'market'} icon={<BarChart3 />} label="Market History DB" onClick={() => setActiveTab('market')} />
          <SidebarButton active={activeTab === 'settings'} icon={<Settings2 />} label="Constraints" onClick={() => setActiveTab('settings')} />
        </div>

        <div style={{ padding: '24px', borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.01)' }}>
          <div style={{ padding: '12px', background: isLiveMode ? 'var(--danger-bg)' : 'rgba(79, 70, 229, 0.1)', border: `1px solid ${isLiveMode ? 'var(--danger)' : 'var(--primary)'}`, borderRadius: '12px', display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
            {isLiveMode ? <ShieldAlert color="var(--danger)" size={20} style={{ flexShrink: 0 }} /> : <Shield color="var(--primary)" size={20} style={{ flexShrink: 0 }} />}
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: isLiveMode ? 'var(--danger)' : 'var(--primary)' }}>
                {isLiveMode ? 'LIVE TRADING MODE' : 'PAPER TRADING ONLY'}
              </p>
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', lineHeight: 1.4 }}>
                {isLiveMode ? 'System is actively routing to broker APIs.' : 'Execution layer is completely simulated.'}
              </p>
              {!isLiveMode && (
                <button onClick={() => alert("SECURITY GATE: Live Mode requires explicit CLI configuration toggle.")} style={{ marginTop: '8px', padding: '4px 8px', background: 'transparent', border: '1px solid var(--primary)', color: 'var(--primary)', borderRadius: '4px', fontSize: '10px', fontWeight: 600 }}>UNLOCK LIVE</button>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* MAIN CONTENT */}
      <main style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-dark)', padding: '32px 48px' }}>

        {/* TOP BAR / STATS */}
        <header className="animate-fade-in" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '40px' }}>
          <div>
            <h2 style={{ fontSize: '28px', fontWeight: 600 }}>Portfolio Command Center</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '4px' }}>Deterministic risk enforcement active.</p>
          </div>

          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px' }}>Trigger Autonomous Agents</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="text"
                  value={targetTicker}
                  onChange={(e) => setTargetTicker(e.target.value)}
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', color: '#fff', padding: '8px 12px', borderRadius: '6px', width: '80px', fontFamily: 'monospace' }}
                />
                <button
                  onClick={triggerAgent}
                  disabled={isSimulating}
                  style={{ background: 'var(--primary)', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '6px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px', opacity: isSimulating ? 0.7 : 1 }}
                >
                  {isSimulating ? <Activity size={16} className="animate-pulse" /> : <Play size={16} />}
                  {isSimulating ? 'Processing...' : 'Run Cycle'}
                </button>
              </div>
            </div>
            <StatCard label="Total Equity" value={`$${accountValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} />
            <div style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '4px' }}>Risk Engine</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--success)', animation: 'pulse-subtle 2s infinite' }}></div>
                <span style={{ fontSize: '15px', fontWeight: 500, color: 'var(--success)' }}>ONLINE</span>
              </div>
            </div>
          </div>
        </header>

        {/* TAB RENDERING */}
        {activeTab === 'dashboard' && (
          <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>

            <section className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Active Paper Positions</h3>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ color: 'var(--text-dark)', fontSize: '12px', textTransform: 'uppercase' }}>
                    <th style={{ paddingBottom: '12px' }}>Asset</th>
                    <th style={{ paddingBottom: '12px' }}>Side</th>
                    <th style={{ paddingBottom: '12px' }}>Shares</th>
                    <th style={{ paddingBottom: '12px' }}>Entry</th>
                    <th style={{ paddingBottom: '12px' }}>Current</th>
                    <th style={{ paddingBottom: '12px' }}>Stop Loss</th>
                    <th style={{ paddingBottom: '12px', textAlign: 'right' }}>PNL %</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 && (
                    <tr><td colSpan="7" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)' }}>No active positions. Run an agent cycle.</td></tr>
                  )}
                  {positions.map(pos => (
                    <tr key={pos.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '16px 0', fontWeight: 600 }}>{pos.ticker}</td>
                      <td style={{ padding: '16px 0' }}><span style={{ background: 'rgba(52, 211, 153, 0.1)', color: '#34D399', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600 }}>{pos.side}</span></td>
                      <td style={{ padding: '16px 0', color: 'var(--text-muted)' }}>{pos.shares}</td>
                      <td style={{ padding: '16px 0', fontFamily: 'monospace' }}>${pos.entry.toFixed(2)}</td>
                      <td style={{ padding: '16px 0', fontFamily: 'monospace' }}>${pos.current.toFixed(2)}</td>
                      <td style={{ padding: '16px 0', fontFamily: 'monospace', color: 'var(--warning)' }}>${pos.stop.toFixed(2)}</td>
                      <td style={{ padding: '16px 0', textAlign: 'right', fontWeight: 600, color: pos.pnl_pct >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                        {pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct.toFixed(2)}%
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

              <ConstraintRow label="Max Daily Loss" value="3.0%" limit="3.0%" />
              <ConstraintRow label="Account Exposure" value="8.4%" limit="100.0%" />
              <ConstraintRow label="Sector Correlation" value="12%" limit="20%" />

              <div style={{ marginTop: '24px', padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', display: 'flex', gap: '12px' }}>
                <Info color="var(--text-muted)" size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  The Multi-Agent system cannot bypass these mathematical boundaries. Any LLM-proposed trade exceeding these configurations is instantly rejected by the Python execution layer.
                </p>
              </div>
            </section>
          </div>
        )}

        {/* MOCK AUDIT TAB */}
        {activeTab === 'audit' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Immutable Execution Journal</h3>

            {auditLogs.length === 0 && <p style={{ color: 'var(--text-muted)' }}>No events recorded for this session yet.</p>}
            {auditLogs.map(log => (
              <div key={log.id} style={{ display: 'flex', gap: '24px', padding: '16px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ color: 'var(--text-dark)', fontFamily: 'monospace', fontSize: '13px' }}>{log.time}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <span style={{ fontWeight: 600 }}>{log.agent}</span>
                    <span style={{
                      fontSize: '10px', fontWeight: 700, padding: '2px 6px', borderRadius: '4px',
                      background: log.action === 'REJECTED' ? 'var(--danger-bg)' : log.action === 'FILLED' ? 'var(--success-bg)' : 'rgba(255,255,255,0.1)',
                      color: log.action === 'REJECTED' ? 'var(--danger)' : log.action === 'FILLED' ? 'var(--success)' : '#fff'
                    }}>{log.action}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>[{log.ticker}]</span>
                  </div>
                  <p style={{ fontSize: '14px', color: 'var(--text-muted)' }}>{log.reason}</p>
                </div>
                <div>
                  <button onClick={() => alert(JSON.stringify(log, null, 2))} style={{ background: 'transparent', border: '1px solid var(--border)', padding: '6px 12px', color: '#fff', borderRadius: '6px', fontSize: '12px', cursor: 'pointer' }}>View JSON</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* MARKET HISTORY DB TAB */}
        {activeTab === 'market' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, margin: 0 }}>Database: Real-Time Price Storage</h3>
              <button
                onClick={clearMarketDatabase}
                style={{ background: 'transparent', color: 'var(--danger)', border: '1px solid var(--danger)', padding: '6px 12px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer' }}
                onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'; }}
                onMouseOut={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                Clear Database
              </button>
            </div>

            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ color: 'var(--text-dark)', fontSize: '12px', textTransform: 'uppercase' }}>
                  <th style={{ paddingBottom: '12px' }}>Request ID</th>
                  <th style={{ paddingBottom: '12px' }}>Timestamp</th>
                  <th style={{ paddingBottom: '12px' }}>Ticker</th>
                  <th style={{ paddingBottom: '12px' }}>Current Price</th>
                  <th style={{ paddingBottom: '12px' }}>VIX Index Pulse</th>
                </tr>
              </thead>
              <tbody>
                {marketDataHistory.length === 0 && (
                  <tr><td colSpan="5" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)' }}>No market data cached in SQLite database yet. Run a Cycle to save rows!</td></tr>
                )}
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

        {/* QUOTE LOOKUP TAB */}
        {activeTab === 'quote' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 500, borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px' }}>Stock Quote & Research</h3>

            <div style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
              <input
                type="text"
                value={quoteTicker}
                onChange={(e) => setQuoteTicker(e.target.value.toUpperCase())}
                placeholder="Enter Ticker (e.g. AAPL)"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', color: '#fff', padding: '10px 16px', borderRadius: '8px', flex: 1, maxWidth: '250px', outline: 'none' }}
                onKeyDown={(e) => e.key === 'Enter' && lookupQuote()}
              />
              <button
                onClick={lookupQuote}
                disabled={quoteLoading}
                style={{ background: 'var(--primary)', color: '#fff', border: 'none', padding: '10px 24px', borderRadius: '8px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', opacity: quoteLoading ? 0.7 : 1 }}
              >
                {quoteLoading ? <Activity size={18} className="animate-pulse" /> : <Search size={18} />}
                {quoteLoading ? 'Searching...' : 'Lookup'}
              </button>
            </div>

            {quoteData && (
              <div className="animate-fade-in" style={{ background: 'rgba(255,255,255,0.02)', padding: '24px', borderRadius: '12px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
                  <div>
                    <h2 style={{ fontSize: '28px', fontWeight: 700, margin: '0 0 4px 0' }}>
                      {quoteData.ticker} <span style={{ fontSize: '18px', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '8px' }}>{quoteData.name}</span>
                    </h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', margin: 0 }}>{quoteData.sector} • {quoteData.industry}</p>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <h2 style={{ fontSize: '32px', fontWeight: 600, margin: 0, color: 'var(--text-dark)' }}>
                      ${quoteData.current_price?.toFixed(2) || 'N/A'}
                    </h2>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                  <StatCard label="Market Cap" value={quoteData.market_cap ? `$${(quoteData.market_cap / 1e9).toFixed(2)}B` : 'N/A'} />
                  <StatCard label="52-Week High" value={quoteData.fiftyTwoWeekHigh ? `$${quoteData.fiftyTwoWeekHigh.toFixed(2)}` : 'N/A'} />
                  <StatCard label="52-Week Low" value={quoteData.fiftyTwoWeekLow ? `$${quoteData.fiftyTwoWeekLow.toFixed(2)}` : 'N/A'} />
                </div>

                <div>
                  <h4 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Company Summary</h4>
                  <p style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--text-dark)', margin: 0 }}>{quoteData.summary}</p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* MARKET MOVERS TAB */}
        {activeTab === 'movers' && (
          <div className="animate-fade-in glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 500, margin: 0 }}>Top Gainers & Losers <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>(via Yahoo Finance API)</span></h3>
              <button
                onClick={fetchMovers}
                disabled={moversLoading}
                style={{ background: 'transparent', color: 'var(--primary)', border: '1px solid var(--primary)', padding: '6px 12px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', opacity: moversLoading ? 0.7 : 1 }}
              >
                {moversLoading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '24px' }}>

              {/* GAINERS */}
              <div>
                <h4 style={{ color: 'var(--success)', fontWeight: 600, marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}><TrendingUp size={16} /> Top 10 Gainers</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {movers.gainers.slice(0, 10).map((m, i) => (
                    <div key={m.ticker} onClick={() => { setQuoteTicker(m.ticker); setActiveTab('quote'); lookupQuote(); }} style={{ background: 'rgba(52, 211, 153, 0.05)', border: '1px solid rgba(52, 211, 153, 0.2)', padding: '12px 16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', transition: 'all 0.2s' }} className="hover:bg-opacity-20">
                      <div>
                        <span style={{ fontWeight: 700, marginRight: '8px' }}>{m.ticker}</span>
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{m.name.substring(0, 25)}{m.name.length > 25 ? '...' : ''}</span>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>${m.price.toFixed(2)}</div>
                        <div style={{ color: 'var(--success)', fontSize: '12px', fontWeight: 600, fontFamily: 'monospace' }}>+{m.change_pct.toFixed(2)}%</div>
                      </div>
                    </div>
                  ))}
                  {(!movers.gainers || movers.gainers.length === 0) && !moversLoading && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>No gainers recorded today.</div>}
                </div>
              </div>

              {/* LOSERS */}
              <div>
                <h4 style={{ color: 'var(--danger)', fontWeight: 600, marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}><TrendingUp size={16} style={{ transform: 'scaleY(-1)' }} /> Top 10 Losers</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {movers.losers.slice(0, 10).map((m, i) => (
                    <div key={m.ticker} onClick={() => { setQuoteTicker(m.ticker); setActiveTab('quote'); lookupQuote(); }} style={{ background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '12px 16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', transition: 'all 0.2s' }}>
                      <div>
                        <span style={{ fontWeight: 700, marginRight: '8px' }}>{m.ticker}</span>
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{m.name.substring(0, 25)}{m.name.length > 25 ? '...' : ''}</span>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>${m.price.toFixed(2)}</div>
                        <div style={{ color: 'var(--danger)', fontSize: '12px', fontWeight: 600, fontFamily: 'monospace' }}>{m.change_pct.toFixed(2)}%</div>
                      </div>
                    </div>
                  ))}
                  {(!movers.losers || movers.losers.length === 0) && !moversLoading && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>No losers recorded today.</div>}
                </div>
              </div>

              {/* ACTIVE / TRENDING */}
              <div>
                <h4 style={{ color: 'var(--primary)', fontWeight: 600, marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}><Activity size={16} /> Most Active</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {movers.actives && movers.actives.slice(0, 10).map((m, i) => (
                    <div key={m.ticker} onClick={() => { setQuoteTicker(m.ticker); setActiveTab('quote'); lookupQuote(); }} style={{ background: 'rgba(79, 70, 229, 0.05)', border: '1px solid rgba(79, 70, 229, 0.2)', padding: '12px 16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', transition: 'all 0.2s' }}>
                      <div>
                        <span style={{ fontWeight: 700, marginRight: '8px' }}>{m.ticker}</span>
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{m.name.substring(0, 20)}{m.name.length > 20 ? '...' : ''}</span>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>${m.price.toFixed(2)}</div>
                        <div style={{ color: m.change_pct >= 0 ? 'var(--success)' : 'var(--danger)', fontSize: '12px', fontWeight: 600, fontFamily: 'monospace' }}>
                          {m.change_pct >= 0 ? '+' : ''}{m.change_pct.toFixed(2)}%
                        </div>
                      </div>
                    </div>
                  ))}
                  {(!movers.actives || movers.actives.length === 0) && !moversLoading && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>No trending data recorded today.</div>}
                </div>
              </div>

            </div>
          </div>
        )}

        {/* DISCLAIMER FOOTER */}
        <footer style={{ marginTop: '48px', padding: '24px', borderTop: '1px solid var(--border)', textAlign: 'center' }}>
          <p style={{ fontSize: '12px', color: 'var(--text-dark)', maxWidth: '800px', margin: '0 auto', lineHeight: 1.6 }}>
            NOT FINANCIAL ADVICE. Agentic Trading architectures carry massive, unpredictable risks. Do not utilize this software with real capital without extensive professional code review.
          </p>
        </footer>

      </main>
    </div>
  );
}

// --- MICRO COMPONENTS ---

function SidebarButton({ icon, label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '12px',
        padding: '12px 16px', width: '100%', background: active ? 'rgba(255,255,255,0.03)' : 'transparent',
        border: 'none', borderRadius: '8px', color: active ? '#fff' : 'var(--text-muted)',
        fontWeight: active ? 500 : 400, transition: 'all 0.2s',
        borderRight: active ? '3px solid var(--primary)' : '3px solid transparent'
      }}
      onMouseOver={(e) => { if (!active) e.currentTarget.style.color = '#fff'; }}
      onMouseOut={(e) => { if (!active) e.currentTarget.style.color = 'var(--text-muted)'; }}
    >
      {React.cloneElement(icon, { size: 18, color: active ? 'var(--primary)' : 'currentColor' })}
      <span>{label}</span>
    </button>
  );
}

function StatCard({ label, value, trend }) {
  return (
    <div style={{ padding: '16px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '12px', minWidth: '160px' }}>
      <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px' }}>{label}</p>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
        <h3 style={{ fontSize: '24px', fontWeight: 600, fontFamily: 'monospace' }}>{value}</h3>
        {trend === 'up' && <TrendingUp size={16} color="var(--success)" style={{ marginBottom: '4px' }} />}
        {trend === 'down' && <TrendingUp size={16} color="var(--danger)" style={{ marginBottom: '4px', transform: 'scaleY(-1)' }} />}
      </div>
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
