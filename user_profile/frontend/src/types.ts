export type Product = {
  id: string
  name: string
  category: string
  brand: string
  price: number
  quality: number
  sustainability: number
}

export type SwipeResponse = {
  product_id: string
  name: string
  accepted: boolean
  feedback: string
}

export type WeightRow = {
  name: string
  value: number
}

export type ModelSnapshot = {
  weights: WeightRow[]
  plots: {
    quality_price: string
    price_sustainability: string
  }
}
