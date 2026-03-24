import React, { useState, useRef } from 'react';

const styles = {
  zone: {
    border: '2px dashed #475569',
    borderRadius: '12px',
    padding: '32px 20px',
    textAlign: 'center',
    cursor: 'pointer',
    transition: 'all 0.2s ease',
    background: '#1e293b',
    position: 'relative',
  },
  zoneHover: {
    border: '2px dashed #6366f1',
    background: '#1e2a47',
  },
  zoneSuccess: {
    border: '2px solid #22c55e',
    background: '#0f2318',
  },
  icon: {
    fontSize: '2.5rem',
    marginBottom: '12px',
    display: 'block',
  },
  title: {
    fontSize: '1rem',
    fontWeight: '600',
    color: '#cbd5e1',
    marginBottom: '6px',
  },
  subtitle: {
    fontSize: '0.8rem',
    color: '#64748b',
    marginBottom: '16px',
  },
  browseBtn: {
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    padding: '8px 20px',
    fontSize: '0.85rem',
    cursor: 'pointer',
    fontWeight: '600',
  },
  fileName: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    marginTop: '12px',
    padding: '8px 16px',
    background: '#162032',
    borderRadius: '8px',
    fontSize: '0.85rem',
    color: '#22c55e',
    fontWeight: '500',
  },
  removeBtn: {
    background: 'transparent',
    border: 'none',
    color: '#ef4444',
    cursor: 'pointer',
    fontSize: '1rem',
    lineHeight: 1,
    padding: '0 2px',
  },
  hiddenInput: {
    display: 'none',
  },
};

export default function UploadZone({ onFileSelect, uploadedFile }) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) validateAndSelect(file);
  };

  const handleInputChange = (e) => {
    const file = e.target.files[0];
    if (file) validateAndSelect(file);
  };

  const validateAndSelect = (file) => {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['pdf', 'docx'].includes(ext)) {
      alert('Only .pdf and .docx files are supported.');
      return;
    }
    onFileSelect(file);
  };

  const handleRemove = (e) => {
    e.stopPropagation();
    onFileSelect(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const zoneStyle = {
    ...styles.zone,
    ...(isDragging ? styles.zoneHover : {}),
    ...(uploadedFile ? styles.zoneSuccess : {}),
  };

  return (
    <div
      style={zoneStyle}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => !uploadedFile && fileInputRef.current?.click()}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx"
        style={styles.hiddenInput}
        onChange={handleInputChange}
      />

      {uploadedFile ? (
        <>
          <span style={styles.icon}>✅</span>
          <div style={styles.title}>Resume Uploaded</div>
          <div style={styles.fileName}>
            <span>📄</span>
            <span>{uploadedFile.name}</span>
            <button style={styles.removeBtn} onClick={handleRemove} title="Remove file">
              ✕
            </button>
          </div>
        </>
      ) : (
        <>
          <span style={styles.icon}>📂</span>
          <div style={styles.title}>Drop your resume here</div>
          <div style={styles.subtitle}>Supports PDF and DOCX formats</div>
          <button
            style={styles.browseBtn}
            onClick={(e) => {
              e.stopPropagation();
              fileInputRef.current?.click();
            }}
          >
            Browse Files
          </button>
        </>
      )}
    </div>
  );
}
