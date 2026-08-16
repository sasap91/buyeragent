import type { Product } from '../types'
import { ProductCard } from './ProductCard'

export function ProductList({
  products,
  onRemove,
  onDone,
}: {
  products: Product[]
  onRemove: (id: string) => void
  onDone: () => void
}) {
  return (
    <div className="product-list">
      {products.length === 0 ? (
        <p className="empty">No products left</p>
      ) : (
        <ul className="product-list-items">
          {products.map((product) => (
            <li key={product.id} className="product-list-item">
              <div className="product-list-card">
                <ProductCard product={product} />
                <button
                  type="button"
                  className="remove-btn"
                  aria-label={`Remove ${product.name}`}
                  onClick={() => onRemove(product.id)}
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="text-btn" onClick={onDone}>
        Done
      </button>
    </div>
  )
}
