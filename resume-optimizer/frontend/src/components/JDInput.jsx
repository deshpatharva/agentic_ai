import React, { useState } from 'react';

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  label: {
    fontSize: '0.85rem',
    fontWeight: '600',
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  textareaWrapper: {
    position: 'relative',
  },
  textarea: {
    width: '100%',
    minHeight: '160px',
    padding: '12px 14px',
    background: '#1e293b',
    border: '1.5px solid #334155',
    borderRadius: '10px',
    color: '#e2e8f0',
    fontSize: '0.875rem',
    resize: 'vertical',
    outline: 'none',
    lineHeight: '1.5',
    fontFamily: 'inherit',
    transition: 'border-color 0.2s',
  },
  charCount: {
    fontSize: '0.75rem',
    color: '#64748b',
    textAlign: 'right',
    marginTop: '4px',
  },
  analyzeBtn: {
    width: '100%',
    padding: '10px',
    background: 'linear-gradient(135deg, #0ea5e9, #6366f1)',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontSize: '0.875rem',
    fontWeight: '600',
    cursor: 'pointer',
    transition: 'opacity 0.2s',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
  },
  analyzeBtnDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  keywordsSection: {
    marginTop: '4px',
  },
  keywordsLabel: {
    fontSize: '0.75rem',
    fontWeight: '600',
    color: '#64748b',
    marginBottom: '8px',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  keywordsCloud: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
    maxHeight: '120px',
    overflowY: 'auto',
    paddingRight: '4px',
  },
  chip: {
    padding: '3px 10px',
    borderRadius: '20px',
    fontSize: '0.75rem',
    fontWeight: '500',
    background: '#1e3a5f',
    color: '#7dd3fc',
    border: '1px solid #1e4a7a',
    whiteSpace: 'nowrap',
  },
  spinner: {
    display: 'inline-block',
    width: '14px',
    height: '14px',
    border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff',
    borderRadius: '50%',
    animation: 'spin 0.6s linear infinite',
  },
};

export default function JDInput({ jdText, setJdText, keywords, onAnalyze, analyzing }) {

  const handleTextareaFocus = (e) => {
    e.target.style.borderColor = '#6366f1';
  };
  const handleTextareaBlur = (e) => {
    e.target.style.borderColor = '#334155';
  };

  const isDisabled = analyzing || jdText.trim().length < 50;

  return (
    <div style={styles.container}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        textarea:focus { border-color: #6366f1 !important; }
      `}</style>

      <label style={styles.label}>Job Description</label>

      <div style={styles.textareaWrapper}>
        <textarea
          style={styles.textarea}
          placeholder="Paste the job description here...&#10;&#10;Include requirements, responsibilities, and skills to get the best keyword extraction."
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          onFocus={handleTextareaFocus}
          onBlur={handleTextareaBlur}
        />
      </div>

      <div style={styles.charCount}>
        {jdText.length.toLocaleString()} characters
      </div>

      <button
        style={{
          ...styles.analyzeBtn,
          ...(isDisabled ? styles.analyzeBtnDisabled : {}),
        }}
        onClick={onAnalyze}
        disabled={isDisabled}
      >
        {analyzing ? (
          <>
            <span style={styles.spinner} />
            Analyzing JD...
          </>
        ) : (
          <>🔍 Analyze Job Description</>
        )}
      </button>

      {keywords && keywords.length > 0 && (
        <div style={styles.keywordsSection}>
          <div style={styles.keywordsLabel}>
            Extracted Keywords ({keywords.length})
          </div>
          <div style={styles.keywordsCloud}>
            {keywords.map((kw, i) => (
              <span key={i} style={styles.chip}>
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
