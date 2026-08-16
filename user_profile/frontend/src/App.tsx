import { useCallback, useState } from 'react'
import productsCsv from '../../examples/products.csv?raw'
import './App.css'
import { Results } from './components/Results'
import { SwipeDeck } from './components/SwipeDeck'
import { parseProducts } from './parseProducts'
import type { SwipeResponse } from './types'

const products = parseProducts(productsCsv)

export default function App() {
  const [index, setIndex] = useState(0)
  const [responses, setResponses] = useState<SwipeResponse[]>([])
  const [exit, setExit] = useState<'left' | 'right' | null>(null)

  const done = index >= products.length

  const onSwipe = useCallback(
    (accepted: boolean) => {
      if (exit !== null || index >= products.length) {
        return
      }
      setExit(accepted ? 'right' : 'left')
    },
    [exit, index],
  )

  const onExitEnd = () => {
    const product = products[index]
    if (!product || exit === null) {
      return
    }
    setResponses((prev) => [
      ...prev,
      { product_id: product.id, name: product.name, accepted: exit === 'right' },
    ])
    setIndex((current) => current + 1)
    setExit(null)
  }

  const restart = () => {
    setIndex(0)
    setResponses([])
    setExit(null)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Product Swipe</h1>
      </header>
      {done ? (
        <Results responses={responses} onRestart={restart} />
      ) : (
        <SwipeDeck
          products={products}
          index={index}
          exit={exit}
          onSwipe={onSwipe}
          onExitEnd={onExitEnd}
        />
      )}
    </div>
  )
}
