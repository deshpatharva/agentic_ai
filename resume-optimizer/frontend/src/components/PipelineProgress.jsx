import React from 'react';

const STAGES = [
  { id: 'upload',     label: 'Upload & Parse',       icon: '📤' },
  { id: 'jd_analysis', label: 'JD Analysis',          icon: '🔍' },
  { id: 'rewrite',    label: 'Rewrite Resume',        icon: '✍️' },
  { id: 'humanize',   label: 'Humanize',              icon: '🤝' },
  { id: 'score',      label: 'Score & Evaluate',      icon: '📊' },
  { id: 'consolidate', label: 'Optimization Loop',    icon: '🔄' },
  { id: 'generate',   label: 'Generate Output',       icon: '📄' },
];

const STAGE_ORDER = STAGES.map((s) => s.id);

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0',
  },
  title: {
    fontSize: '0.75rem',
    fontWeight: '600',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: '12px',
  },
  stageRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '8px 0',
    position: 'relative',
  },
  connector: {
    position: 'absolute',
    left: '15px',
    top: '32px',
    width: '2px',
    height: '20px',
    background: '#334155',
    zIndex: 0,
  },
  connectorDone: {
    background: '#22c55e',
  },
  dot: {
    width: '30px',
    height: '30px',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    fontSize: '0.75rem',
    zIndex: 1,
    border: '2px solid #334155',
    background: '#0f172a',
    transition: 'all 0.3s ease',
  },
  dotDone: {
    background: '#166534',
    border: '2px solid #22c55e',
  },
  dotActive: {
    background: '#1e3a5f',
    border: '2px solid #6366f1',
    boxShadow: '0 0 10px rgba(99,102,241,0.5)',
  },
  dotPending: {
    background: '#0f172a',
    border: '2px solid #334155',
  },
  stageLabel: {
    fontSize: '0.875rem',
    fontWeight: '500',
    color: '#94a3b8',
    transition: 'color 0.3s ease',
  },
  stageLabelActive: {
    color: '#a5b4fc',
    fontWeight: '600',
  },
  stageLabelDone: {
    color: '#4ade80',
  },
  iterationBadge: {
    marginLeft: 'auto',
    padding: '2px 8px',
    background: '#1e3a2f',
    border: '1px solid #16a34a',
    borderRadius: '12px',
    fontSize: '0.7rem',
    color: '#4ade80',
    fontWeight: '600',
  },
  pulsingDot: {
    display: 'inline-block',
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    background: '#6366f1',
    animation: 'pulse 1s infinite',
    marginRight: '2px',
  },
};

function getStageStatus(stageId, currentStage, completedStages) {
  if (completedStages.includes(stageId)) return 'done';
  if (stageId === currentStage) return 'active';
  return 'pending';
}

export default function PipelineProgress({ currentStage, completedStages, iteration, pipelineStatus }) {
  const completed = completedStages || [];

  return (
    <div style={styles.container}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>

      <div style={styles.title}>Pipeline Stages</div>

      {STAGES.map((stage, idx) => {
        const status = getStageStatus(stage.id, currentStage, completed);
        const isLast = idx === STAGES.length - 1;

        const dotStyle = {
          ...styles.dot,
          ...(status === 'done' ? styles.dotDone : {}),
          ...(status === 'active' ? styles.dotActive : {}),
          ...(status === 'pending' ? styles.dotPending : {}),
        };

        const labelStyle = {
          ...styles.stageLabel,
          ...(status === 'active' ? styles.stageLabelActive : {}),
          ...(status === 'done' ? styles.stageLabelDone : {}),
        };

        return (
          <div key={stage.id} style={{ position: 'relative' }}>
            <div style={styles.stageRow}>
              <div style={dotStyle}>
                {status === 'done' ? '✓' : stage.icon}
              </div>

              <span style={labelStyle}>
                {status === 'active' && (
                  <span style={styles.pulsingDot} />
                )}
                {stage.label}
              </span>

              {stage.id === 'consolidate' && iteration > 1 && (
                <span style={styles.iterationBadge}>
                  Iter {iteration}
                </span>
              )}
            </div>

            {!isLast && (
              <div
                style={{
                  ...styles.connector,
                  ...(status === 'done' ? styles.connectorDone : {}),
                }}
              />
            )}
          </div>
        );
      })}

      {pipelineStatus === 'done' && (
        <div style={{
          marginTop: '12px',
          padding: '8px 14px',
          background: '#0f2318',
          border: '1px solid #22c55e',
          borderRadius: '8px',
          fontSize: '0.8rem',
          color: '#4ade80',
          textAlign: 'center',
          fontWeight: '600',
        }}>
          ✅ Pipeline Complete!
        </div>
      )}
    </div>
  );
}
