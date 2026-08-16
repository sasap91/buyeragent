import { useEffect, useRef } from 'react'
import type { Product } from '../types'
import { ProductCard } from './ProductCard'

export function ProductList({
  products,
  removingId,
  reason,
  onReasonChange,
  onStartRemove,
  onCancelRemove,
  onConfirmRemove,
  onDone,
}: {
  products: Product[]
  removingId: string | null
  reason: string
  onReasonChange: (value: string) => void
  onStartRemove: (id: string) => void
  onCancelRemove: () => void
  onConfirmRemove: () => void
  onDone: () => void
}) {
  const reasonRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (removingId) {
      reasonRef.current?.focus()
    }
  }, [removingId])

  return (
    <div className="product-list">
      {products.length === 0 ? (
        <p className="empty">No products left</p>
      ) : (
        <ul className="product-list-items">
          {products.map((product) => {
            const removing = product.id === removingId
            return (
              <li key={product.id} className="product-list-item">
                <div className="product-list-card">
                  <ProductCard product={product} />
                  <button
                    type="button"
                    className="remove-btn"
                    aria-label={`Remove ${product.name}`}
                    aria-expanded={removing}
                    onClick={() =>
                      removing ? onCancelRemove() : onStartRemove(product.id)
                    }
                  >
                    ×
                  </button>
                </div>
                {removing ? (
                  <form
                    className="reason-bar"
                    onSubmit={(event) => {
                      event.preventDefault()
                      onConfirmRemove()
                    }}
                  >
                    <label className="feedback-field">
                      <span>Reason</span>
                      <input
                        ref={reasonRef}
                        type="text"
                        value={reason}
                        onChange={(event) => onReasonChange(event.target.value)}
                        placeholder="Why remove this product?"
                        autoComplete="off"
                      />
                    </label>
                    <div className="reason-actions">
                      <button type="submit" className="text-btn">
                        Remove
                      </button>
                      <button
                        type="button"
                        className="text-btn ghost"
                        onClick={onCancelRemove}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
      <button type="button" className="text-btn" onClick={onDone}>
        Done
      </button>
    </div>
  )
}
