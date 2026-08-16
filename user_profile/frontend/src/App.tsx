import { useEffect, useMemo, useState } from 'react'
import { fetchPairs, updateModel } from './api'
import './App.css'
import { ModelPanel } from './components/ModelPanel'
import { ProductList } from './components/ProductList'
import { Results } from './components/Results'
import type { ComparisonCatalog, ModelSnapshot, Product } from './types'

const BUYER_ID = 'buyer-maya'
const HOME_URL = import.meta.env.VITE_HOME_URL ?? 'http://127.0.0.1:8765'

function uniqueProducts(catalog: ComparisonCatalog): Product[] {
  const seen = new Map<string, Product>()
  for (const pair of catalog.pairs) {
    if (!seen.has(pair.left.id)) {
      seen.set(pair.left.id, pair.left)
    }
    if (!seen.has(pair.right.id)) {
      seen.set(pair.right.id, pair.right)
    }
  }
  return [...seen.values()]
}

export default function App() {
  const [catalog, setCatalog] = useState<ComparisonCatalog | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [rejectedIds, setRejectedIds] = useState<string[]>([])
  const [done, setDone] = useState(false)
  const [model, setModel] = useState<ModelSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const catalogProducts = useMemo(
    () => (catalog ? uniqueProducts(catalog) : []),
    [catalog],
  )

  const products = useMemo(
    () => catalogProducts.filter((product) => !rejectedIds.includes(product.id)),
    [catalogProducts, rejectedIds],
  )

  useEffect(() => {
    const controller = new AbortController()
    fetchPairs(controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) {
          return
        }
        setCatalog(payload)
        setCatalogError(null)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setCatalogError(err instanceof Error ? err.message : 'Failed to load products')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!catalog) {
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    updateModel(BUYER_ID, rejectedIds, controller.signal)
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
  }, [catalog, rejectedIds])

  const remove = (id: string) => {
    setRejectedIds((current) => (current.includes(id) ? current : [...current, id]))
  }

  const restart = () => {
    setRejectedIds([])
    setDone(false)
    setModel(null)
    setError(null)
  }

  return (
    <div className="app">
      <header className="app-header">
        <a className="home-btn" href={HOME_URL}>
          Home
        </a>
        <h1>Path A · new buyer</h1>
      </header>
      <div className="app-body comparison-layout">
        {catalogError ? (
          <p className="model-error">{catalogError}</p>
        ) : done ? (
          <Results
            profile={model?.profile ?? null}
            rejectedCount={rejectedIds.length}
            onRestart={restart}
          />
        ) : catalog ? (
          <ProductList products={products} onRemove={remove} onDone={() => setDone(true)} />
        ) : (
          <p className="empty">Loading products…</p>
        )}
        <ModelPanel model={model} loading={loading} error={error} />
      </div>
    </div>
  )
}
