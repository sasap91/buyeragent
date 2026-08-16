"""Write the module's deliverables to disk as JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from buyer_history.schema import BuyerProfileBundle


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export_bundle(bundle: BuyerProfileBundle, out_dir: str | Path) -> dict[str, Path]:
    """Emit normalized transactions, the buyer profile, and category/item profiles."""
    out = Path(out_dir)

    written = {
        "normalized_transactions": _write(
            out / "normalized_transactions.json",
            {
                "buyer_id": bundle.buyer_id,
                "as_of": bundle.as_of.isoformat(),
                "count": len(bundle.transactions),
                "transactions": [t.to_dict() for t in bundle.transactions],
            },
        ),
        "excluded_transactions": _write(
            out / "excluded_transactions.json",
            {
                "count": len(bundle.excluded),
                "note": "Removed from preference learning; retained so exclusions stay auditable.",
                "excluded": [e.to_dict() for e in bundle.excluded],
            },
        ),
        "buyer_profile": _write(out / "buyer_profile.json", bundle.to_dict()),
        "category_profiles": _write(
            out / "category_profiles.json",
            {
                "buyer_id": bundle.buyer_id,
                "version": bundle.version,
                "count": len(bundle.category_profiles),
                "profiles": {k: v.to_dict() for k, v in sorted(bundle.category_profiles.items())},
            },
        ),
        "item_profiles": _write(
            out / "item_profiles.json",
            {
                "buyer_id": bundle.buyer_id,
                "version": bundle.version,
                "count": len(bundle.item_profiles),
                "profiles": {k: v.to_dict() for k, v in sorted(bundle.item_profiles.items())},
            },
        ),
        "mandate_hints": _write(
            out / "mandate_hints.json",
            {
                "general": bundle.general.to_mandate_hints(),
                "by_category": {
                    k: v.to_mandate_hints() for k, v in sorted(bundle.categories.items())
                },
            },
        ),
    }
    return written
