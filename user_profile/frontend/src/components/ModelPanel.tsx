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
  return (
    <aside className="model-panel">
      <h2>Preference model</h2>
      {loading ? <p className="model-status">Updating…</p> : null}
      {error ? <p className="model-error">{error}</p> : null}
      {model ? (
        <>
          <h3>Weights</h3>
          <div className="weight-table-wrap">
            <table className="weight-table">
              <tbody>
                {model.weights.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td>{row.value.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Quality × price</h3>
          <img
            className="model-plot"
            src={`data:image/png;base64,${model.plots.quality_price}`}
            alt="Quality versus price decision boundary"
          />
          <h3>Price × sustainability</h3>
          <img
            className="model-plot"
            src={`data:image/png;base64,${model.plots.price_sustainability}`}
            alt="Price versus sustainability decision boundary"
          />
        </>
      ) : null}
    </aside>
  )
}
