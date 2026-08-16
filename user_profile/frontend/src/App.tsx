import { useEffect, useState } from 'react'
import productsCsv from '../../examples/products.csv?raw'
import { updateModel } from './api'
import './App.css'
import { ModelPanel } from './components/ModelPanel'
import { ProductList } from './components/ProductList'
import { Results } from './components/Results'
import { parseProducts } from './parseProducts'
import type { ModelSnapshot, Product, SwipeResponse } from './types'

const catalog = parseProducts(productsCsv)

function rejectResponse(product: Product): SwipeResponse {
  return {
    product_id: product.id,
    name: product.name,
    accepted: false,
    feedback: '',
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
  const [responses, setResponses] = useState<SwipeResponse[]>([])
  const [done, setDone] = useState(false)
  const [model, setModel] = useState<ModelSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const remainingIds = remaining.map((item) => item.id)
    const rejectedIds = responses
      .filter((item) => !item.accepted)
      .map((item) => item.product_id)
    setLoading(true)
    setError(null)
    updateModel(remainingIds, rejectedIds, controller.signal)
      .then((snapshot) => {
        if (controller.signal.aborted) {
          return
        }
        setModel(snapshot)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setLoading(false)
        setError(err instanceof Error ? err.message : 'Failed to update model')
      })
    return () => controller.abort()
  }, [remaining, responses])

  const remove = (id: string) => {
    const product = remaining.find((item) => item.id === id)
    if (!product) {
      return
    }
    const next = remaining.filter((item) => item.id !== product.id)
    setResponses((prev) => [...prev, rejectResponse(product)])
    setRemaining(next)
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
    setResponses([])
    setDone(false)
    setModel(null)
    setError(null)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Products</h1>
      </header>
      <div className="app-body">
        {done ? (
          <Results responses={responses} onRestart={restart} />
        ) : (
          <ProductList products={remaining} onRemove={remove} onDone={finish} />
        )}
        <ModelPanel model={model} loading={loading} error={error} />
      </div>
    </div>
  )
}
