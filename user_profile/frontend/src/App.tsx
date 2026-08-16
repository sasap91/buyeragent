import { useState } from 'react'
import productsCsv from '../../examples/products.csv?raw'
import './App.css'
import { ProductList } from './components/ProductList'
import { Results } from './components/Results'
import { parseProducts } from './parseProducts'
import type { Product, SwipeResponse } from './types'

const catalog = parseProducts(productsCsv)

function rejectResponse(product: Product, reason: string): SwipeResponse {
  return {
    product_id: product.id,
    name: product.name,
    accepted: false,
    feedback: reason.trim(),
  }
}

function acceptResponse(product: Product): SwipeResponse {
  return {
    product_id: product.id,
    name: product.name,
    accepted: true,
    feedback: '',
  }
}

export default function App() {
  const [remaining, setRemaining] = useState<Product[]>(catalog)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [responses, setResponses] = useState<SwipeResponse[]>([])
  const [done, setDone] = useState(false)

  const startRemove = (id: string) => {
    setRemovingId(id)
    setReason('')
  }

  const cancelRemove = () => {
    setRemovingId(null)
    setReason('')
  }

  const confirmRemove = () => {
    const product = remaining.find((item) => item.id === removingId)
    if (!product) {
      return
    }
    const next = remaining.filter((item) => item.id !== product.id)
    setResponses((prev) => [...prev, rejectResponse(product, reason)])
    setRemaining(next)
    setRemovingId(null)
    setReason('')
    if (next.length === 0) {
      setDone(true)
    }
  }

  const finish = () => {
    setResponses((prev) => [...prev, ...remaining.map(acceptResponse)])
    setDone(true)
  }

  const restart = () => {
    setRemaining(catalog)
    setRemovingId(null)
    setReason('')
    setResponses([])
    setDone(false)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Products</h1>
      </header>
      {done ? (
        <Results responses={responses} onRestart={restart} />
      ) : (
        <ProductList
          products={remaining}
          removingId={removingId}
          reason={reason}
          onReasonChange={setReason}
          onStartRemove={startRemove}
          onCancelRemove={cancelRemove}
          onConfirmRemove={confirmRemove}
          onDone={finish}
        />
      )}
    </div>
  )
}
