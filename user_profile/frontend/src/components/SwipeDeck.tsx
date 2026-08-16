import { useEffect } from 'react'
import type { Product } from '../types'
import { ProductCard } from './ProductCard'

export function SwipeDeck({
  products,
  index,
  exit,
  onSwipe,
  onExitEnd,
}: {
  products: Product[]
  index: number
  exit: 'left' | 'right' | null
  onSwipe: (accepted: boolean) => void
  onExitEnd: () => void
}) {
  const current = products[index]
  const next = products[index + 1]
  const locked = exit !== null

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        onSwipe(false)
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        onSwipe(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onSwipe])

  if (!current) {
    return null
  }

  return (
    <div className="swipe-deck">
      <p className="progress">
        {index + 1} / {products.length}
      </p>
      <div className="card-stack">
        {next ? (
          <div className="card-layer card-layer-next">
            <ProductCard product={next} />
          </div>
        ) : null}
        <div className="card-layer card-layer-current">
          <ProductCard product={current} exit={exit} onExitEnd={onExitEnd} />
        </div>
      </div>
      <div className="swipe-actions">
        <button
          type="button"
          className="swipe-btn reject"
          onClick={() => onSwipe(false)}
          disabled={locked}
          aria-label="Reject"
        >
          ←
        </button>
        <button
          type="button"
          className="swipe-btn accept"
          onClick={() => onSwipe(true)}
          disabled={locked}
          aria-label="Accept"
        >
          →
        </button>
      </div>
      <p className="hint">Left to reject · Right to accept</p>
    </div>
  )
}
