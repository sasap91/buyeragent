import type { SwipeResponse } from '../types'

function downloadResponses(responses: SwipeResponse[]) {
  const blob = new Blob([JSON.stringify({ responses }, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'swipes.json'
  link.click()
  URL.revokeObjectURL(url)
}

export function Results({
  responses,
  onRestart,
}: {
  responses: SwipeResponse[]
  onRestart: () => void
}) {
  const accepted = responses.filter((item) => item.accepted)
  const rejected = responses.filter((item) => !item.accepted)

  return (
    <div className="results">
      <h2>Your picks</h2>
      <p className="results-summary">
        {accepted.length} accepted · {rejected.length} rejected
      </p>
      <div className="results-columns">
        <section>
          <h3>Accepted</h3>
          {accepted.length === 0 ? (
            <p className="empty">None</p>
          ) : (
            <ul>
              {accepted.map((item) => (
                <li key={item.product_id}>
                  {item.name}
                  {item.feedback ? <span className="feedback-note">{item.feedback}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h3>Rejected</h3>
          {rejected.length === 0 ? (
            <p className="empty">None</p>
          ) : (
            <ul>
              {rejected.map((item) => (
                <li key={item.product_id}>
                  {item.name}
                  {item.feedback ? <span className="feedback-note">{item.feedback}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <pre className="results-json">{JSON.stringify({ responses }, null, 2)}</pre>
      <div className="results-actions">
        <button type="button" className="text-btn" onClick={() => downloadResponses(responses)}>
          Download JSON
        </button>
        <button type="button" className="text-btn ghost" onClick={onRestart}>
          Restart
        </button>
      </div>
    </div>
  )
}
