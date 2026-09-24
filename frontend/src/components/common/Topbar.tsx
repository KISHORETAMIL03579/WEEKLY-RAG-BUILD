import React from 'react';

interface TopbarProps {
  backendMode: string;
  backendStatus: 'checking' | 'healthy' | 'error';
  docsCount: number;
  retrievalMode: string;
  topK: number;
  temperature: number;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

export const Topbar: React.FC<TopbarProps> = ({
  backendMode,
  backendStatus,
  docsCount,
  retrievalMode,
  topK,
  temperature,
  sidebarOpen,
  onToggleSidebar,
}) => {
  const statusLabel =
    backendStatus === 'healthy' ? 'Connected' : backendStatus === 'checking' ? 'Connecting...' : 'Disconnected';

  return (
    <header className="topbar">
      <div className="topbar-logo">
        <button
          type="button"
          className={`logo-toggle-btn ${sidebarOpen ? 'active' : 'collapsed'}`}
          onClick={onToggleSidebar}
          title={sidebarOpen ? 'Hide Sidebar (Collapse)' : 'Show Sidebar (Open)'}
          aria-label={sidebarOpen ? 'Collapse sidebar navigation' : 'Expand sidebar navigation'}
        >
          <span className="hamburger-line"></span>
          <span className="hamburger-line"></span>
          <span className="hamburger-line"></span>
        </button>
        <span className="logo-name">Ask My Docs</span>
        <span className="logo-version">v1 · Python</span>
      </div>

      <div className="topbar-spacer"></div>

      <a
        href="/eval?tab=policy"
        className="eval-btn"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontWeight: 600,
          background: 'rgba(16, 185, 129, 0.15)',
          borderColor: '#10b981',
          color: '#10b981',
          marginRight: '6px',
        }}
      >
        👔 HR Policy Assistant ↗
      </a>

      <a
        href="/eval?tab=judge"
        className="eval-btn"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontWeight: 600,
          background: 'rgba(59, 130, 246, 0.15)',
          borderColor: 'var(--accent)',
          color: '#60a5fa',
        }}
      >
        ⚖️ Evaluator ↗
      </a>

      <div className="topbar-stat">
        <span
          className={`status-dot status-${backendStatus}`}
          title={`Backend status: ${statusLabel}`}
          aria-label={`Backend status: ${statusLabel}`}
        ></span>
        <span>Docs: {docsCount}</span>
        <span className="topbar-mode">K={topK} · T={temperature.toFixed(2)}</span>
        {retrievalMode && (
          <span className="topbar-mode topbar-mode-hybrid">
            mode: {retrievalMode}
          </span>
        )}
        <span className="topbar-mode topbar-mode-backend">
          {backendMode || 'qdrant'}
        </span>
      </div>
    </header>
  );
};

