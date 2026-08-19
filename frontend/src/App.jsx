import { useState } from 'react';
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
  const [message, setMessage] = useState('');
  const [resume, setResume] = useState('');
  const [loading, setLoading] = useState(false);
  const [liveStep, setLiveStep] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [expandedJobs, setExpandedJobs] = useState({});

  const toggleExpand = (index) => {
    setExpandedJobs(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

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
        body: JSON.stringify({ message, resume }),
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
  const resumeOver = resume.length > MAX_RESUME;

  // Detect vague resumes — no experience duration signals (years, digits+, seniority words)
  const EXP_SIGNALS = /\b(\d+\+?\s*(year|yr|yrs|months?)|senior|lead|principal|junior|intern|manager|director|fresher|entry.?level)/i;
  const resumeIsVague = resume.trim().length >= 50 && !EXP_SIGNALS.test(resume);

  const canSubmit = message.trim().length >= 5 && resume.trim().length >= 50 && !loading && !msgOver && !resumeOver;
  const status = result ? (STATUS_CONFIG[result.status] || STATUS_CONFIG.no_match) : null;

  // All jobs returned from backend are already >= 50% (filtered server-side)
  const allJobs = result?.verdict?.verdicts || [];
  const highMatches = allJobs.filter(j => j.fit_score >= 80);
  const mediumMatches = allJobs.filter(j => j.fit_score >= 50 && j.fit_score < 80);

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
              <label>Paste your resume</label>
              <span className={`char-count ${resumeOver ? 'char-over' : resume.length > MAX_RESUME * 0.9 ? 'char-warn' : ''}`}>
                {resume.length}/{MAX_RESUME}
              </span>
            </div>
            <textarea
              rows={11}
              value={resume}
              maxLength={MAX_RESUME}
              onChange={(e) => setResume(e.target.value)}
              placeholder="Paste your full resume text here..."
              className={resumeOver ? 'input-over' : ''}
            />
            {resumeOver && (
              <p className="field-error">Resume exceeds 6,000 characters. Please trim to the most relevant sections.</p>
            )}
            {!resumeOver && resumeIsVague && (
              <div className="resume-tip">
                <span className="resume-tip-icon">✏️</span>
                <span>For more accurate scoring, include experience details — e.g. <em>&quot;3 years in sales&quot;</em> or <em>&quot;2+ yrs as a designer&quot;</em>. Without this, the agent will assume entry-level.</span>
              </div>
            )}
          </div>

          <button onClick={handleSubmit} disabled={!canSubmit}>
            {loading ? 'Analyzing…' : 'Analyze Fit'}
          </button>
        </div>

        {/* RIGHT: live status / results */}
        <div className="right-pane">
          {!loading && !result && !error && (
            <div className="placeholder-box">
              <p>Fill in the form and click "Analyze Fit" — your agent's live progress and verdict will appear here.</p>
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