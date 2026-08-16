import type { BuyerPreferenceProfile } from '../types'

function downloadProfile(profile: BuyerPreferenceProfile) {
  const blob = new Blob([JSON.stringify(profile, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${profile.buyer_id}-preference-profile.json`
  link.click()
  URL.revokeObjectURL(url)
}

function SignalRow({
  label,
  value,
  extra,
}: {
  label: string
  value: string
  extra?: string
}) {
  return (
    <div className="profile-row">
      <span className="profile-label">{label}</span>
      <span className="profile-value">
        {value}
        {extra ? <span className="profile-extra">{extra}</span> : null}
      </span>
    </div>
  )
}

export function Results({
  profile,
  rejectedCount,
  onRestart,
}: {
  profile: BuyerPreferenceProfile | null
  rejectedCount: number
  onRestart: () => void
}) {
  if (!profile) {
    return (
      <div className="results">
        <h2>Building your profile…</h2>
        <p className="results-summary">{rejectedCount} items rejected</p>
      </div>
    )
  }

  const brands =
    profile.preferred_brands.length > 0
      ? profile.preferred_brands.map((item) => item.value).join(' > ')
      : 'None yet'
  const conditions =
    profile.condition_preferences.length > 0
      ? profile.condition_preferences.map((item) => item.value).join(', ')
      : 'No condition preference'
  const rules =
    profile.hard_rule_candidates.length > 0
      ? profile.hard_rule_candidates
          .map((item) => item.rationale || item.candidate_id)
          .join('; ')
      : 'None'

  return (
    <div className="results">
      <h2>Buyer preference profile</h2>
      <p className="results-summary">
        {rejectedCount} items rejected · {profile.buyer_id} · {profile.category}
      </p>
      <div className="profile-grid">
        <SignalRow label="Price sensitivity" value={profile.price_sensitivity.value} />
        <SignalRow label="Quality importance" value={profile.quality_importance.value} />
        <SignalRow
          label="Delivery importance"
          value={profile.delivery_importance.value}
        />
        <SignalRow
          label="Returns importance"
          value={profile.return_policy_importance.value}
        />
        <SignalRow
          label="Merchant trust"
          value={profile.merchant_trust_importance.value}
        />
        <SignalRow label="Preferred brands" value={brands} />
        <SignalRow label="Condition" value={conditions} />
        <SignalRow label="Hard-rule candidates" value={rules} />
      </div>
      <pre className="results-json">{JSON.stringify(profile, null, 2)}</pre>
      <div className="results-actions">
        <button
          type="button"
          className="text-btn"
          onClick={() => downloadProfile(profile)}
        >
          Download profile
        </button>
        <button type="button" className="text-btn ghost" onClick={onRestart}>
          Restart
        </button>
      </div>
    </div>
  )
}
