// Where this app finds the backend it talks to.
//
// window.__API_URL__ is set by a tiny config.js file that gets *generated
// at container startup* (see Dockerfile + docker-entrypoint.sh), not baked
// into the JavaScript bundle at build time. That's deliberate: it means
// the exact same built Docker image can be pointed at any backend URL
// (local, staging, a freshly-recreated cluster with a new IP) just by
// changing an environment variable on the container - no rebuild needed.
//
// Locally, with `npm run dev`, that config.js file doesn't exist, so we
// fall back to a Vite env var (from a local .env file), and finally to
// localhost as a last resort.
declare global {
  interface Window {
    __API_URL__?: string
  }
}

const API_URL =
  window.__API_URL__ || import.meta.env.VITE_API_URL || 'http://localhost:8000'

export type Role = 'clinician' | 'researcher'

export interface AskResponse {
  answer: string
  citations: string[]
  uncited_claims: string[]
  fabricated_citations: string[]
}

export async function askQuestion(question: string, role: Role): Promise<AskResponse> {
  const res = await fetch(`${API_URL}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, role }),
  })
  if (!res.ok) {
    throw new Error(`Request failed (HTTP ${res.status}). Is the backend reachable?`)
  }
  return res.json()
}
