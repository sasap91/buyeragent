import type { ModelSnapshot } from './types'

export async function updateModel(
  remainingIds: string[],
  rejectedIds: string[],
  signal?: AbortSignal,
): Promise<ModelSnapshot> {
  const response = await fetch('/api/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      remaining_ids: remainingIds,
      rejected_ids: rejectedIds,
    }),
    signal,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Update failed (${response.status})`)
  }
  return response.json()
}
