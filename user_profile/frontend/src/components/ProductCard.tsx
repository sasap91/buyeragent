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

export function ProductCard({
  product,
  exit,
  onExitEnd,
}: {
  product: Product
  exit?: 'left' | 'right' | null
  onExitEnd?: () => void
}) {
  const className = ['product-card', exit ? `exit-${exit}` : '']
    .filter(Boolean)
    .join(' ')

  return (
    <article className={className} onAnimationEnd={onExitEnd}>
      {exit === 'left' ? <div className="stamp stamp-nope">Nope</div> : null}
      {exit === 'right' ? <div className="stamp stamp-like">Like</div> : null}
      <div className="card-category">{product.category}</div>
      <h2 className="card-name">{product.name}</h2>
      <p className="card-brand">{product.brand}</p>
      <p className="card-price">{formatPrice(product.price)}</p>
      <ScoreBar label="Quality" value={product.quality} />
      <ScoreBar label="Sustainability" value={product.sustainability} />
    </article>
  )
}
