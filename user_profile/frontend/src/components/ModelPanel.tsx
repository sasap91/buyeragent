import type { ModelSnapshot } from '../types'

export function ModelPanel({
  model,
  loading,
  error,
}: {
  model: ModelSnapshot | null
  loading: boolean
  error: string | null
}) {
  const plots = model?.plots
  const weights = model?.weights ?? []

  return (
    <aside className="model-panel">
      <h2>Preference model</h2>
      {loading ? <p className="model-status">Updating…</p> : null}
      {error ? <p className="model-error">{error}</p> : null}
      {model ? (
        <>
          <h3>Weights</h3>
          {weights.length === 0 ? (
            <p className="empty">No weights yet</p>
          ) : (
            <div className="weight-table-wrap">
              <table className="weight-table">
                <tbody>
                  {weights.map((row) => (
                    <tr key={row.name}>
                      <td>{row.name}</td>
                      <td>{row.value.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {plots?.quality_price ? (
            <>
              <h3>Quality × price</h3>
              <img
                className="model-plot"
                src={`data:image/png;base64,${plots.quality_price}`}
                alt="Quality versus price decision boundary"
              />
            </>
          ) : null}
          {plots?.price_sustainability ? (
            <>
              <h3>Price × sustainability</h3>
              <img
                className="model-plot"
                src={`data:image/png;base64,${plots.price_sustainability}`}
                alt="Price versus sustainability decision boundary"
              />
            </>
          ) : null}
        </>
      ) : null}
    </aside>
  )
}
