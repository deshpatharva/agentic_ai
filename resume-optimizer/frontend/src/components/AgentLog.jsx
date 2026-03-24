import React, { useEffect, useRef } from 'react';

const EVENT_COLORS = {
  stage:      { bg: '#1e3a5f', border: '#1d4ed8', text: '#93c5fd', icon: '⚙️' },
  score:      { bg: '#0f2318', border: '#15803d', text: '#4ade80', icon: '📊' },
  average:    { bg: '#1a1f2e', border: '#4f46e5', text: '#a5b4fc', icon: '📈' },
  iterate:    { bg: '#1f1a0e', border: '#d97706', text: '#fbbf24', icon: '🔄' },
  error:      { bg: '#1f0f0f', border: '#dc2626', text: '#f87171', icon: '❌' },
  done:       { bg: '#180f2a', border: '#7c3aed', text: '#c4b5fd', icon: '✅' },
  consolidate:{ bg: '#1f1a0e', border: '#d97706', text: '#fbbf24', icon: '🔗' },
  finalize:   { bg: '#0f2318', border: '#15803d', text: '#4ade80', icon: '🏁' },
  generate:   { bg: '#1e3a5f', border: '#1d4ed8', text: '#93c5fd', icon: '📄' },
};

const DEFAULT_COLOR = { bg: '#1a1f2e', border: '#334155', text: '#94a3b8', icon: '•' };

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '8px',
  },
  title: {
    fontSize: '0.75rem',
    fontWeight: '600',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
  count: {
    fontSize: '0.7rem',
    color: '#475569',
    background: '#1e293b',
    padding: '2px 8px',
    borderRadius: '10px',
  },
  logWindow: {
    flex: 1,
    overflowY: 'auto',
    background: '#0b1120',
    borderRadius: '10px',
    border: '1px solid #1e293b',
    padding: '10px',
    minHeight: '200px',
    maxHeight: '380px',
    display: 'flex',
    flexDirection: 'column',
    gap: '5px',
    scrollBehavior: 'smooth',
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: '#334155',
    fontSize: '0.85rem',
    gap: '8px',
    padding: '20px',
    textAlign: 'center',
  },
  logEntry: {
    borderRadius: '6px',
    padding: '6px 10px',
    fontSize: '0.78rem',
    lineHeight: '1.4',
    display: 'flex',
    gap: '8px',
    alignItems: 'flex-start',
    flexShrink: 0,
    border: '1px solid transparent',
  },
  entryIcon: {
    flexShrink: 0,
    fontSize: '0.85rem',
    lineHeight: '1.4',
  },
  entryContent: {
    flex: 1,
    minWidth: 0,
  },
  entryTime: {
    fontSize: '0.65rem',
    opacity: 0.5,
    marginLeft: '4px',
  },
  scoreInline: {
    fontWeight: '700',
    fontSize: '0.85rem',
  },
};

function formatLogEntry(event, index) {
  const colors = EVENT_COLORS[event.type] || DEFAULT_COLOR;
  const time = event.timestamp
    ? new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '';

  let content = null;

  if (event.type === 'score') {
    const score = event.score ?? '?';
    const color = score >= 85 ? '#4ade80' : score >= 70 ? '#fbbf24' : '#f87171';
    content = (
      <>
        <strong style={{ color: colors.text }}>{event.platform}</strong>
        {': '}
        <span style={{ ...styles.scoreInline, color }}>{score}/100</span>
        {event.feedback && event.feedback.length > 0 && (
          <div style={{ marginTop: '3px', opacity: 0.75, fontSize: '0.72rem' }}>
            Missing: {event.feedback.slice(0, 4).join(', ')}
          </div>
        )}
      </>
    );
  } else if (event.type === 'average') {
    const score = event.score ?? '?';
    const color = score >= 85 ? '#4ade80' : score >= 70 ? '#fbbf24' : '#f87171';
    content = (
      <>
        <strong style={{ color: colors.text }}>Average Score</strong>
        {': '}
        <span style={{ ...styles.scoreInline, color }}>{score}/100</span>
        <span style={{ color: '#64748b' }}> (Iteration {event.iteration})</span>
      </>
    );
  } else if (event.type === 'done') {
    content = (
      <>
        <strong style={{ color: colors.text }}>{event.message}</strong>
        {event.final_score && (
          <span style={{ color: '#64748b' }}> — Final score: {event.final_score}/100</span>
        )}
      </>
    );
  } else if (event.type === 'iterate') {
    content = (
      <strong style={{ color: colors.text }}>{event.message}</strong>
    );
  } else {
    content = (
      <span style={{ color: colors.text }}>{event.message || JSON.stringify(event)}</span>
    );
  }

  return (
    <div
      key={index}
      style={{
        ...styles.logEntry,
        background: colors.bg,
        borderColor: colors.border,
      }}
    >
      <span style={styles.entryIcon}>{colors.icon}</span>
      <div style={styles.entryContent}>
        {content}
        {time && <span style={styles.entryTime}>{time}</span>}
      </div>
    </div>
  );
}

export default function AgentLog({ logs }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.title}>Agent Activity Log</div>
        {logs && logs.length > 0 && (
          <div style={styles.count}>{logs.length} events</div>
        )}
      </div>

      <div style={styles.logWindow}>
        {!logs || logs.length === 0 ? (
          <div style={styles.emptyState}>
            <span style={{ fontSize: '2rem' }}>🤖</span>
            <span>Agent logs will appear here once the pipeline starts...</span>
          </div>
        ) : (
          <>
            {logs.map((event, i) => formatLogEntry({ ...event, timestamp: event.timestamp || Date.now() }, i))}
            <div ref={bottomRef} />
          </>
        )}
      </div>
    </div>
  );
}
