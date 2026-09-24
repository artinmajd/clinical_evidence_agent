import { useState, FormEvent } from 'react'
import { askQuestion, AskResponse, Role } from './api'

export default function App() {
  const [question, setQuestion] = useState('')
  const [role, setRole] = useState<Role>('clinician')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AskResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = question.trim()
    if (!trimmed) return

    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await askQuestion(trimmed, role)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  const hasGuardrailNote =
    result != null &&
    (result.uncited_claims.length > 0 || result.fabricated_citations.length > 0)

  return (
    <div className="page">
      <header className="header">
        <h1>Clinical Evidence Agent</h1>
        <p>
          Ask a question about the ingested clinical trial corpus. Answers
          are grounded in retrieved trial data and every claim is checked
          for a real citation before you see it.
        </p>
      </header>

      <form className="ask-form" onSubmit={handleSubmit}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What dosage of semaglutide was used in the obesity trials?"
          rows={3}
        />
        <div className="form-row">
          <label htmlFor="role">Role</label>
          {/* Mirrors the backend's real access-control roles (see
              guardrails/access_control.py) - "researcher" only sees
              public trial data, "clinician" also sees the synthetic
              restricted subset. Picking one here actually changes what
              the backend is allowed to retrieve, not just a UI label. */}
          <select id="role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="clinician">Clinician (full access)</option>
            <option value="researcher">Researcher (public data only)</option>
          </select>
          <button type="submit" disabled={loading || !question.trim()}>
            {loading ? 'Asking…' : 'Ask'}
          </button>
        </div>
      </form>

      {error && <div className="card error-card">{error}</div>}

      {result && (
        <div className="card answer-card">
          <p className="answer-text">{result.answer}</p>

          {result.citations.length > 0 && (
            <div className="citations">
              {result.citations.map((c) => (
                <span key={c} className="citation-pill">
                  {c}
                </span>
              ))}
            </div>
          )}

          {hasGuardrailNote && (
            <div className="guardrail-warning">
              <strong>Guardrail note:</strong>{' '}
              {result.uncited_claims.length > 0 &&
                `${result.uncited_claims.length} claim(s) had no supporting citation. `}
              {result.fabricated_citations.length > 0 &&
                `${result.fabricated_citations.length} citation(s) could not be verified against the corpus.`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
