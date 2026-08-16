export type ComparisonChoice = 'LEFT' | 'RIGHT' | 'EITHER' | 'NEITHER'

export type Product = {
  id: string
  name: string
  category: string
  brand: string
  price: number
  quality: number
  sustainability: number
  condition?: string | null
  delivery_days?: number | null
  return_window_days?: number | null
  merchant?: string | null
}

export type ComparisonPair = {
  pair_id: string
  tradeoff: string
  prompt: string
  left: Product
  right: Product
}

export type ComparisonCatalog = {
  category: string
  demo_pair_count: number
  pairs: ComparisonPair[]
}

export type ComparisonAnswer = {
  pair_id: string
  choice: ComparisonChoice
}

export type ImportanceLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN'

export type PreferenceSignal<T> = {
  value: T
  numeric_weight: string | number
  source: string
  confidence: string | number
}

export type HardRuleCandidate = {
  candidate_id: string
  kind: string
  operator: string
  expected: unknown
  source: string
  confidence: string | number
  requires_confirmation: boolean
  rationale: string | null
}

export type BuyerPreferenceProfile = {
  schema_version: string
  buyer_id: string
  category: string
  price_sensitivity: PreferenceSignal<ImportanceLevel>
  quality_importance: PreferenceSignal<ImportanceLevel>
  delivery_importance: PreferenceSignal<ImportanceLevel>
  return_policy_importance: PreferenceSignal<ImportanceLevel>
  merchant_trust_importance: PreferenceSignal<ImportanceLevel>
  preferred_brands: PreferenceSignal<string>[]
  disliked_brands: PreferenceSignal<string>[]
  condition_preferences: PreferenceSignal<string>[]
  hard_rule_candidates: HardRuleCandidate[]
  created_at: string
}

export type WeightRow = {
  name: string
  value: number
}

export type ModelSnapshot = {
  profile: BuyerPreferenceProfile
  weights: WeightRow[]
  plots: {
    quality_price: string
    price_sustainability: string
  } | null
}
