import type { Product } from './types'

const REQUIRED_COLUMNS = [
  'id',
  'name',
  'category',
  'brand',
  'price',
  'quality',
  'sustainability',
] as const

export function parseProducts(csv: string): Product[] {
  const lines = csv.trim().split(/\r?\n/)
  if (lines.length < 2) {
    return []
  }

  const header = lines[0].split(',').map((column) => column.trim())
  const index = Object.fromEntries(header.map((column, i) => [column, i]))

  for (const column of REQUIRED_COLUMNS) {
    if (!(column in index)) {
      throw new Error(`Missing CSV column: ${column}`)
    }
  }

  return lines
    .slice(1)
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      const cols = line.split(',')
      return {
        id: cols[index.id].trim(),
        name: cols[index.name].trim(),
        category: cols[index.category].trim(),
        brand: cols[index.brand].trim(),
        price: Number(cols[index.price]),
        quality: Number(cols[index.quality]),
        sustainability: Number(cols[index.sustainability]),
      }
    })
}
