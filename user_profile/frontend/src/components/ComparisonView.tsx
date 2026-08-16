import type { ComparisonChoice, ComparisonPair } from '../types'
import { ProductCard } from './ProductCard'

export function ComparisonView({
  pair,
  index,
  total,
  onChoose,
}: {
  pair: ComparisonPair
  index: number
  total: number
  onChoose: (choice: ComparisonChoice) => void
}) {
  return (
    <div className="comparison">
      <p className="comparison-progress">
        Comparison {index + 1} of {total}
      </p>
      <p className="comparison-prompt">{pair.prompt}</p>
      <div className="comparison-cards">
        <div className="comparison-side">
          <span className="comparison-label">A</span>
          <ProductCard product={pair.left} />
        </div>
        <div className="comparison-side">
          <span className="comparison-label">B</span>
          <ProductCard product={pair.right} />
        </div>
      </div>
      <div className="comparison-actions">
        <button type="button" className="choice-btn" onClick={() => onChoose('LEFT')}>
          Product A
        </button>
        <button type="button" className="choice-btn" onClick={() => onChoose('RIGHT')}>
          Product B
        </button>
        <button
          type="button"
          className="choice-btn ghost"
          onClick={() => onChoose('EITHER')}
        >
          Either
        </button>
        <button
          type="button"
          className="choice-btn ghost"
          onClick={() => onChoose('NEITHER')}
        >
          Neither
        </button>
      </div>
    </div>
  )
}
