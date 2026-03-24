import React from 'react';

const SCORE_CARDS = [
  {
    key: 'ats',
    label: 'ATS Match',
    icon: '🤖',
    feedbackKey: 'missing_keywords',
    feedbackLabel: 'Missing Keywords',
    secondaryKey: 'matched_keywords',
    secondaryLabel: 'Matched',
  },
  {
    key: 'impact',
    label: 'Impact Score',
    icon: '⚡',
    feedbackKey: 'suggestions',
    feedbackLabel: 'Suggestions',
    secondaryKey: 'weak_bullets',
    secondaryLabel: 'Weak Bullets',
  },
  {
    key: 'skills_gap',
    label: 'Skills Gap',
    icon: '🎯',
    feedbackKey: 'missing_skills',
    feedbackLabel: 'Missing Skills',
    secondaryKey: 'matched_skills',
    secondaryLabel: 'Matched Skills',
  },
  {
    key: 'readability',
    label: 'Readability',
    icon: '📖',
    feedbackKey: 'issues',
    feedbackLabel: 'Issues',
    secondaryKey: 'strengths',
    secondaryLabel: 'Strengths',
  },
];

function getScoreColor(score) {
  if (score >= 85) return '#22c55e';
  if (score >= 70) return '#eab308';
  return '#ef4444';
}

function getScoreBg(score) {
  if (score >= 85) return '#0f2318';
  if (score >= 70) return '#1f1a0e';
  return '#1f0f0f';
}

function ScoreBar({ score }) {
  const color = getScoreColor(score);
  return (
    <div style={{
      height: '6px',
      background: '#1e293b',
      borderRadius: '3px',
      overflow: 'hidden',
      margin: '6px 0',
    }}>
      <div style={{
        height: '100%',
        width: `${score}%`,
        background: `linear-gradient(90deg, ${color}88, ${color})`,
        borderRadius: '3px',
        transition: 'width 0.8s ease',
      }} />
    </div>
  );
}

function ScoreCard({ card, data }) {
  const score = data?.score ?? null;
  const feedback = data?.[card.feedbackKey] ?? [];
  const secondary = data?.[card.secondaryKey] ?? [];
  const color = score !== null ? getScoreColor(score) : '#475569';
  const bg = score !== null ? getScoreBg(score) : '#1e293b';

  return (
    <div style={{
      background: bg,
      border: `1.5px solid ${color}44`,
      borderRadius: '12px',
      padding: '14px',
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      transition: 'all 0.3s ease',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '1rem' }}>{card.icon}</span>
          <span style={{ fontSize: '0.78rem', fontWeight: '600', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {card.label}
          </span>
        </div>
        <span style={{
          fontSize: '1.5rem',
          fontWeight: '800',
          color: score !== null ? color : '#334155',
          lineHeight: 1,
        }}>
          {score !== null ? score : '--'}
        </span>
      </div>

      {score !== null && <ScoreBar score={score} />}

      {feedback.length > 0 && (
        <div>
          <div style={{ fontSize: '0.65rem', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>
            {card.feedbackLabel}
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {feedback.slice(0, 4).map((item, i) => (
              <li key={i} style={{
                fontSize: '0.72rem',
                color: '#94a3b8',
                padding: '2px 6px',
                background: '#0f172a',
                borderRadius: '4px',
                borderLeft: `2px solid ${color}66`,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {secondary.length > 0 && (
        <div style={{ fontSize: '0.65rem', color: '#4ade8088' }}>
          {card.secondaryLabel}: {secondary.slice(0, 3).join(', ')}
          {secondary.length > 3 && ` +${secondary.length - 3} more`}
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: '0.75rem',
    fontWeight: '600',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '10px',
  },
  averageCard: {
    borderRadius: '12px',
    padding: '16px 20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  avgLabel: {
    fontSize: '0.85rem',
    fontWeight: '700',
    color: '#e2e8f0',
  },
  avgSubLabel: {
    fontSize: '0.72rem',
    color: '#94a3b8',
    marginTop: '2px',
  },
  avgScore: {
    fontSize: '2.5rem',
    fontWeight: '900',
    lineHeight: 1,
  },
  iterBadge: {
    padding: '3px 10px',
    borderRadius: '12px',
    fontSize: '0.72rem',
    fontWeight: '600',
    background: '#1e3a2f',
    border: '1px solid #16a34a',
    color: '#4ade80',
  },
  downloadBtn: {
    width: '100%',
    padding: '12px',
    background: 'linear-gradient(135deg, #16a34a, #15803d)',
    color: '#fff',
    border: 'none',
    borderRadius: '10px',
    fontSize: '0.9rem',
    fontWeight: '700',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    transition: 'transform 0.1s, box-shadow 0.2s',
    boxShadow: '0 4px 15px rgba(22,163,74,0.3)',
    letterSpacing: '0.02em',
  },
};

export default function ScoreDashboard({ scores, iteration, downloadUrl, pipelineStatus }) {
  const averageScore = scores?.average ?? null;
  const avgColor = averageScore !== null ? getScoreColor(averageScore) : '#475569';

  const handleDownload = () => {
    if (downloadUrl) {
      const a = document.createElement('a');
      a.href = `http://localhost:8000${downloadUrl}`;
      a.download = 'optimized_resume.docx';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.title}>Score Dashboard</div>
        {iteration > 0 && (
          <div style={styles.iterBadge}>Iteration {iteration}</div>
        )}
      </div>

      {/* Average Score Card */}
      {averageScore !== null && (
        <div style={{
          ...styles.averageCard,
          background: getScoreBg(averageScore),
          border: `2px solid ${avgColor}55`,
          boxShadow: `0 0 20px ${avgColor}22`,
        }}>
          <div>
            <div style={styles.avgLabel}>Overall Score</div>
            <div style={styles.avgSubLabel}>Average across all scorers</div>
          </div>
          <div style={{ ...styles.avgScore, color: avgColor }}>
            {averageScore}
            <span style={{ fontSize: '1rem', fontWeight: '500', color: '#64748b' }}>/100</span>
          </div>
        </div>
      )}

      {/* 4 Score Cards */}
      <div style={styles.grid}>
        {SCORE_CARDS.map((card) => (
          <ScoreCard
            key={card.key}
            card={card}
            data={scores?.[card.key] ?? null}
          />
        ))}
      </div>

      {/* Download Button */}
      {pipelineStatus === 'done' && downloadUrl && (
        <button
          style={styles.downloadBtn}
          onClick={handleDownload}
          onMouseOver={(e) => {
            e.currentTarget.style.transform = 'translateY(-1px)';
            e.currentTarget.style.boxShadow = '0 6px 20px rgba(22,163,74,0.4)';
          }}
          onMouseOut={(e) => {
            e.currentTarget.style.transform = 'translateY(0)';
            e.currentTarget.style.boxShadow = '0 4px 15px rgba(22,163,74,0.3)';
          }}
        >
          ⬇️ Download Optimized Resume (.docx)
        </button>
      )}
    </div>
  );
}
