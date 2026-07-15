import { useState } from 'react';
import './App.css';

const STATUS_CONFIG = {
  approved: { label: '✅ Approved', className: 'badge-approved' },
  low_confidence: { label: '⚠️ Low Confidence', className: 'badge-low' },
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

  const handleSubmit = async () => {
    setError(null);
    setResult(null);
    setLoading(true);
    setLiveStep('Starting...');

    try {
        const response = await fetch(`${API_URL}/analyze-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, resume })
      });

      const reader = response.body.getReader();
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

  const canSubmit = message.trim().length >= 5 && resume.trim().length >= 50 && !loading;
  const status = result ? STATUS_CONFIG[result.status] : null;

  return (
    <div className="app">
      <header className="hero">
        <span className="eyebrow">Agentic AI · Job Fit</span>
        <h1>AI Job-Fit Analyzer</h1>
      </header>

      <div className="layout">
        {/* LEFT: the form */}
        <div className="card">
          <div className="field">
            <label>What are you looking for?</label>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="e.g. Find me a remote backend engineer job"
            />
          </div>

          <div className="field">
            <label>Paste your resume</label>
            <textarea
              rows={11}
              value={resume}
              onChange={(e) => setResume(e.target.value)}
              placeholder="Paste your full resume text here..."
            />
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
      <div className="skeleton-circle shimmer"></div>
    </div>
    <div className="skeleton-line shimmer" style={{ width: '30%', height: '10px' }}></div>
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
            <div className="card result-card">
              <span className={`badge ${status.className}`}>{status.label}</span>

              {result.verdict ? (
                <>
                  <div className="result-header">
                    <div>
                      <h2>{result.verdict.job_title}</h2>
                      <p className="company">{result.verdict.company}</p>
                    </div>
                    <FitGauge score={result.verdict.fit_score} />
                  </div>

                  <div className="skills-block">
                    <span className="skills-label match">Matching</span>
                    <div className="chips">
                      {result.verdict.matching_skills?.map((s) => (
                        <span key={s} className="chip chip-match">{s}</span>
                      ))}
                    </div>
                  </div>

                  <div className="skills-block">
                    <span className="skills-label missing">Missing</span>
                    <div className="chips">
                      {result.verdict.missing_skills?.map((s) => (
                        <span key={s} className="chip chip-missing">{s}</span>
                      ))}
                    </div>
                  </div>

                  <p className="reasoning">{result.verdict.reasoning}</p>
                </>
              ) : (
                <p className="reasoning">{result.message}</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;