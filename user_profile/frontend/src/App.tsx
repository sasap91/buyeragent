import { useEffect, useMemo, useState } from 'react'
import { fetchPairs, updateModel } from './api'
import './App.css'
import { ComparisonView } from './components/ComparisonView'
import { ModelPanel } from './components/ModelPanel'
import { Results } from './components/Results'
import type {
  ComparisonAnswer,
  ComparisonCatalog,
  ComparisonChoice,
  ModelSnapshot,
} from './types'

const BUYER_ID = 'buyer-maya'

export default function App() {
  const [catalog, setCatalog] = useState<ComparisonCatalog | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [index, setIndex] = useState(0)
  const [comparisons, setComparisons] = useState<ComparisonAnswer[]>([])
  const [done, setDone] = useState(false)
  const [model, setModel] = useState<ModelSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const demoPairs = useMemo(
    () => (catalog ? catalog.pairs.slice(0, catalog.demo_pair_count) : []),
    [catalog],
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
        setCatalogError(err instanceof Error ? err.message : 'Failed to load comparisons')
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
    updateModel(BUYER_ID, comparisons, controller.signal)
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
  }, [catalog, comparisons])

  const choose = (choice: ComparisonChoice) => {
    const pair = demoPairs[index]
    if (!pair) {
      return
    }
    const next = [...comparisons, { pair_id: pair.pair_id, choice }]
    setComparisons(next)
    if (next.length >= demoPairs.length) {
      setDone(true)
    } else {
      setIndex((current) => current + 1)
    }
  }

  const restart = () => {
    setIndex(0)
    setComparisons([])
    setDone(false)
    setModel(null)
    setError(null)
  }

  const pair = demoPairs[index]

  return (
    <div className="app">
      <header className="app-header">
        <h1>MandateLab · Cold start</h1>
      </header>
      <div className="app-body comparison-layout">
        {catalogError ? (
          <p className="model-error">{catalogError}</p>
        ) : done ? (
          <Results
            profile={model?.profile ?? null}
            comparisons={comparisons}
            onRestart={restart}
          />
        ) : pair ? (
          <ComparisonView
            pair={pair}
            index={index}
            total={demoPairs.length}
            onChoose={choose}
          />
        ) : (
          <p className="empty">Loading comparisons…</p>
        )}
        <ModelPanel model={model} loading={loading} error={error} />
      </div>
    </div>
  )
}
