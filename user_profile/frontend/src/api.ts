import type { ComparisonAnswer, ComparisonCatalog, ModelSnapshot } from './types'

export async function fetchPairs(signal?: AbortSignal): Promise<ComparisonCatalog> {
  const response = await fetch('/api/pairs', { signal })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Failed to load comparisons (${response.status})`)
  }
  return response.json()
}

export async function updateModel(
  buyerId: string,
  comparisons: ComparisonAnswer[],
  signal?: AbortSignal,
): Promise<ModelSnapshot> {
  const response = await fetch('/api/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      buyer_id: buyerId,
      comparisons,
    }),
    signal,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Update failed (${response.status})`)
  }
  return response.json()
}
