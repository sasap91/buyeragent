import type { Product } from '../types'

function formatPrice(price: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(price)
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const percent = Math.round(value * 100)
  return (
    <div className="score-bar">
      <div className="score-bar-header">
        <span>{label}</span>
        <span>{percent}%</span>
      </div>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function formatCondition(condition: string | null | undefined): string | null {
  if (!condition) {
    return null
  }
  return condition.charAt(0) + condition.slice(1).toLowerCase()
}

export function ProductCard({ product }: { product: Product }) {
  const condition = formatCondition(product.condition)
  const delivery =
    product.delivery_days != null ? `${product.delivery_days}-day delivery` : null
  const returns =
    product.return_window_days != null
      ? product.return_window_days === 0
        ? 'Final sale'
        : `${product.return_window_days}-day returns`
      : null

  return (
    <article className="product-card">
      <div className="card-category">{product.category}</div>
      <h2 className="card-name">{product.name}</h2>
      <p className="card-brand">{product.brand}</p>
      <p className="card-price">{formatPrice(product.price)}</p>
      <ul className="card-meta">
        {condition ? <li>{condition}</li> : null}
        {delivery ? <li>{delivery}</li> : null}
        {returns ? <li>{returns}</li> : null}
        {product.merchant ? <li>{product.merchant}</li> : null}
      </ul>
      <ScoreBar label="Quality" value={product.quality} />
      <ScoreBar label="Sustainability" value={product.sustainability} />
    </article>
  )
}
