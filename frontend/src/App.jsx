import { useState, useRef } from 'react';
import './App.css';

const STATUS_CONFIG = {
  approved: { label: '✅ Approved', className: 'badge-approved' },
  low_confidence: { label: '⚠️ Partial Match (<50%)', className: 'badge-low' },
  no_match: { label: '🔍 No Matches', className: 'badge-neutral' },
  failed: { label: '❌ Failed', className: 'badge-failed' },
  no_action: { label: 'ℹ️ No Action', className: 'badge-neutral' },
  invalid_input: { label: '⚠️ Invalid Input', className: 'badge-low' },
};

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

function FitGauge({ score }) {
  const angle = (score / 100) * 360;
  return (
    <div className="gauge" style={{ '--angle': `${angle}deg` }}>
      <div className="gauge-inner">
        <span className="gauge-score">{score}</span>
        <span className="gauge-max">/ 100</span>
      </div>
    </div>
  );
}

function App() {
  const [inputMode, setInputMode] = useState('pdf'); // 'pdf' | 'text'
  const [message, setMessage] = useState('');
  const [pdfText, setPdfText] = useState('');
  const [pastedText, setPastedText] = useState('');
  const [pdfFile, setPdfFile] = useState(null);
  const [isExtractingPdf, setIsExtractingPdf] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [showExtractedPreview, setShowExtractedPreview] = useState(false);

  const [loading, setLoading] = useState(false);
  const [liveStep, setLiveStep] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [expandedJobs, setExpandedJobs] = useState({});

  const fileInputRef = useRef(null);

  const toggleExpand = (index) => {
    setExpandedJobs(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  const handlePdfUpload = async (file) => {
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please select a valid PDF document (.pdf).');
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      setError('PDF file exceeds 5MB limit. Please upload a smaller file.');
      return;
    }

    setError(null);
    setPdfFile(file);
    setIsExtractingPdf(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`${API_URL}/extract-pdf`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to extract text from PDF');
      }

      setPdfText(data.text);
      setPastedText(''); // Clear any previous pasted text when PDF is uploaded
      setShowExtractedPreview(false);
    } catch (err) {
      setError(err.message || 'Error reading PDF');
      setPdfFile(null);
      setPdfText('');
    } finally {
      setIsExtractingPdf(false);
    }
  };

  const handlePastedTextChange = (e) => {
    const text = e.target.value;
    setPastedText(text);
    // If user enters text in the paste box, clear any uploaded PDF
    if (text.trim() && (pdfFile || pdfText)) {
      setPdfFile(null);
      setPdfText('');
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      handlePdfUpload(file);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const file = e.dataTransfer.files?.[0];
    if (file) {
      handlePdfUpload(file);
    }
  };

  const handleRemovePdf = (e) => {
    e.stopPropagation();
    setPdfFile(null);
    setPdfText('');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const activeResume = inputMode === 'pdf' ? pdfText : pastedText;

  const handleSubmit = async () => {
    setError(null);
    setResult(null);
    setExpandedJobs({});
    setLoading(true);
    setLiveStep('Starting...');

    try {
      const res = await fetch(`${API_URL}/analyze-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, resume: activeResume }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Request failed');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'step') {
              setLiveStep(event.label);
            } else if (event.type === 'final') {
              setResult(event.result);
            }
          }
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const MAX_MESSAGE = 200;
  const MAX_RESUME = 6000;
  const msgOver = message.length > MAX_MESSAGE;
  const activeResumeOver = activeResume.length > MAX_RESUME;

  const canSubmit = message.trim().length >= 5 && activeResume.trim().length >= 50 && !loading && !isExtractingPdf && !msgOver && !activeResumeOver;
  const status = result ? (STATUS_CONFIG[result.status] || STATUS_CONFIG.no_match) : null;

  // All jobs returned from backend are already >= 50% (filtered server-side)
  const allJobs = result?.verdict?.verdicts || [];
  const highMatches = allJobs.filter(j => j.fit_score >= 80);
  const mediumMatches = allJobs.filter(j => j.fit_score >= 50 && j.fit_score < 80);

  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  return (
    <div className="app">
      <header className="hero">
        <span className="eyebrow">Agentic AI · Job Fit</span>
        <h1>AI Job-Fit Analyzer</h1>
      </header>

      <div className="layout">
        {/* LEFT: the form */}
        <div className="card form-card">
          <div className="field">
            <div className="label-row">
              <label>What are you looking for?</label>
              <span className={`char-count ${msgOver ? 'char-over' : ''}`}>{message.length}/{MAX_MESSAGE}</span>
            </div>
            <input
              type="text"
              value={message}
              maxLength={MAX_MESSAGE}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="e.g. Find me a remote backend engineer job"
              className={msgOver ? 'input-over' : ''}
            />
          </div>

          <div className="field">
            <div className="label-row">
              <label>Your Resume</label>
              <div className="tab-pill-group">
                <button
                  type="button"
                  className={`tab-pill ${inputMode === 'pdf' ? 'active' : ''}`}
                  onClick={() => setInputMode('pdf')}
                >
                  📄 Upload PDF
                </button>
                <button
                  type="button"
                  className={`tab-pill ${inputMode === 'text' ? 'active' : ''}`}
                  onClick={() => setInputMode('text')}
                >
                  ✏️ Paste Text
                </button>
              </div>
            </div>

            {inputMode === 'pdf' ? (
              <div className="pdf-upload-container">
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  accept=".pdf,application/pdf"
                  className="file-input-hidden"
                />

                {!pdfFile && (
                  <div
                    className={`dropzone ${isDragging ? 'dragging' : ''} ${isExtractingPdf ? 'extracting' : ''}`}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {isExtractingPdf ? (
                      <div className="dropzone-loading">
                        <div className="spinner"></div>
                        <p className="dropzone-text">Extracting resume text from PDF...</p>
                      </div>
                    ) : (
                      <>
                        <div className="dropzone-icon">📥</div>
                        <p className="dropzone-main-text">
                          <strong>Click to upload</strong> or drag and drop your resume PDF
                        </p>
                        <p className="dropzone-sub-text">PDF format only • Max 5MB</p>
                      </>
                    )}
                  </div>
                )}

                {pdfFile && (
                  <div className="uploaded-file-card">
                    <div className="file-info-main">
                      <div className="file-icon">📄</div>
                      <div className="file-details">
                        <span className="file-name" title={pdfFile.name}>{pdfFile.name}</span>
                        <span className="file-meta">
                          {formatFileSize(pdfFile.size)} • {pdfText.length.toLocaleString()} characters extracted
                        </span>
                      </div>
                      <button
                        type="button"
                        className="file-remove-btn"
                        onClick={handleRemovePdf}
                        title="Remove file"
                      >
                        ✕
                      </button>
                    </div>

                    {pdfText && (
                      <div className="extracted-preview-wrapper">
                        <div
                          className="preview-toggle-header"
                          onClick={() => setShowExtractedPreview(!showExtractedPreview)}
                        >
                          <span>{showExtractedPreview ? 'Hide Extracted Resume' : 'View Extracted Resume'}</span>
                          <span>{showExtractedPreview ? '▲' : '▼'}</span>
                        </div>

                        {showExtractedPreview && (
                          <div className="extracted-preview-box">
                            <textarea
                              rows={8}
                              value={pdfText}
                              maxLength={MAX_RESUME}
                              onChange={(e) => setPdfText(e.target.value)}
                              placeholder="Extracted resume text..."
                              className="extracted-textarea"
                            />
                            <span className="preview-tip">You can edit the extracted text directly if needed.</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {inputMode === 'pdf' && pdfText.length > MAX_RESUME && (
                  <p className="field-error">Extracted resume exceeds 6,000 characters. Please trim or upload a shorter resume.</p>
                )}
              </div>
            ) : (
              <div className="text-resume-container">
                <div className="label-row sub-label-row">
                  <span className="sub-label">Full resume text</span>
                  <span className={`char-count ${pastedText.length > MAX_RESUME ? 'char-over' : pastedText.length > MAX_RESUME * 0.9 ? 'char-warn' : ''}`}>
                    {pastedText.length}/{MAX_RESUME}
                  </span>
                </div>
                <textarea
                  rows={11}
                  value={pastedText}
                  maxLength={MAX_RESUME}
                  onChange={handlePastedTextChange}
                  placeholder="Paste your full resume text here..."
                  className={pastedText.length > MAX_RESUME ? 'input-over' : ''}
                />
                {pastedText.length > MAX_RESUME && (
                  <p className="field-error">Resume exceeds 6,000 characters. Please trim to the most relevant sections.</p>
                )}
              </div>
            )}
          </div>

          <button onClick={handleSubmit} disabled={!canSubmit}>
            {loading ? 'Analyzing…' : isExtractingPdf ? 'Extracting PDF…' : 'Analyze Fit'}
          </button>
        </div>

        {/* RIGHT: live status / results */}
        <div className="right-pane">
          {!loading && !result && !error && (
            <div className="placeholder-box">
              <p>Upload your resume PDF or paste text, enter your role target, and click "Analyze Fit" — your agent's live progress and verdict will appear here.</p>
            </div>
          )}

          {loading && (
            <div className="skeleton-card">
              <p className="live-step">{liveStep}</p>
              <div className="skeleton-badge shimmer"></div>
              <div className="skeleton-row">
                <div className="skeleton-text-block">
                  <div className="skeleton-line shimmer" style={{ width: '70%' }}></div>
                  <div className="skeleton-line shimmer" style={{ width: '40%', height: '12px' }}></div>
                </div>
                <div className="skeleton-gauge shimmer"></div>
              </div>
              <div className="skeleton-chips">
                <div className="skeleton-chip shimmer"></div>
                <div className="skeleton-chip shimmer"></div>
                <div className="skeleton-chip shimmer"></div>
              </div>
              <div className="skeleton-line shimmer" style={{ width: '100%' }}></div>
              <div className="skeleton-line shimmer" style={{ width: '95%' }}></div>
              <div className="skeleton-line shimmer" style={{ width: '60%' }}></div>
            </div>
          )}

          {error && <div className="error-box">⚠️ {error}</div>}

          {result && (
            <div className="results-container">
              <div className="status-header">
                <span className={`badge ${status.className}`}>{status.label}</span>
                {allJobs.length > 0 && (
                  <span className="results-count">
                    {highMatches.length > 0 && `${highMatches.length} High`}
                    {highMatches.length > 0 && mediumMatches.length > 0 && ' · '}
                    {mediumMatches.length > 0 && `${mediumMatches.length} Moderate`}
                    {highMatches.length === 0 && mediumMatches.length === 0 && `${allJobs.length} Partial (<50%)`}
                  </span>
                )}
              </div>

              {allJobs.length > 0 ? (
                <div className="job-list">
                  {highMatches.length === 0 && mediumMatches.length === 0 && (
                    <div className="advisory-box">
                      <span className="advisory-icon">💡</span>
                      <div>
                        <strong>No high-confidence matches (≥50%) found</strong>
                        <p>Showing the closest available listings below with identified gaps so you can see what skills were required:</p>
                      </div>
                    </div>
                  )}

                  {allJobs.map((job, idx) => {
                    const isExpanded = !!expandedJobs[idx];
                    const isHigh = job.fit_score >= 80;
                    const isMed = job.fit_score >= 50 && job.fit_score < 80;

                    return (
                      <div key={idx} className={`card job-card ${isExpanded ? 'expanded' : ''}`}>
                        <div className="job-card-header" onClick={() => toggleExpand(idx)}>
                          <div className="job-title-info">
                            <div className="title-row">
                              <h3>{job.job_title}</h3>
                              <span className={`tier-pill ${isHigh ? 'tier-high' : isMed ? 'tier-med' : 'tier-low'}`}>
                                {isHigh ? 'High Match' : isMed ? 'Moderate' : 'Low Match'}
                              </span>
                            </div>
                            <p className="company">{job.company}</p>
                          </div>
                          <div className="job-card-right">
                            <FitGauge score={job.fit_score} />
                            <span className="expand-arrow">{isExpanded ? '▲' : '▼'}</span>
                          </div>
                        </div>

                        {isExpanded && (
                          <div className="job-card-details">
                            <div className="skills-block">
                              <span className="skills-label match">Matching Skills</span>
                              <div className="chips">
                                {job.matching_skills?.map((s) => (
                                  <span key={s} className="chip chip-match">{s}</span>
                                ))}
                                {(!job.matching_skills || job.matching_skills.length === 0) && (
                                  <span className="no-skills">None explicitly matched in resume</span>
                                )}
                              </div>
                            </div>

                            <div className="skills-block">
                              <span className="skills-label missing">Missing / Desired Skills</span>
                              <div className="chips">
                                {job.missing_skills?.map((s) => (
                                  <span key={s} className="chip chip-missing">{s}</span>
                                ))}
                                {(!job.missing_skills || job.missing_skills.length === 0) && (
                                  <span className="no-skills">No major gaps identified</span>
                                )}
                              </div>
                            </div>

                            <div className="reasoning-block">
                              <span className="reasoning-label">Fit Analysis</span>
                              <p className="reasoning">{job.reasoning}</p>
                            </div>

                            {job.url && (
                              <a href={job.url} target="_blank" rel="noopener noreferrer" className="apply-btn">
                                View & Apply Job ↗
                              </a>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="card result-card">
                  <div className="advisory-box">
                    <span className="advisory-icon">🔍</span>
                    <div>
                      <strong>No listings in your field right now</strong>
                      <p>
                        {result.status === 'low_confidence'
                          ? 'The live remote job boards don\'t currently have listings in your specific field. All available listings were in unrelated professions (e.g., marketing, copywriting, sales) and were filtered out to avoid misleading results. Try again later or broaden your search keywords.'
                          : result.message || 'No live remote listings currently matched ≥ 50% for your skillset. Try adjusting your search query or using broader role keywords.'}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;