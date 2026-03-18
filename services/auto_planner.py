"""Auto-generate a default analysis plan from dataset metadata.

Deterministic (no LLM cost): uses auto_detect groups + heuristics to pick
sensible default operations.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Keywords for detecting variable roles
DEMO_KEYWORDS = {"gender", "sex", "age", "region", "city", "country", "income", "education",
                  "genero", "sexo", "edad", "region", "ciudad", "pais", "ingreso", "educacion",
                  "occupation", "ocupacion", "marital", "estado_civil"}
NPS_KEYWORDS = {"nps", "recommend", "recomendar", "promoter", "likelihood"}
WEIGHT_KEYWORDS = {"weight", "wt", "pond", "ponder"}


class AutoPlanner:
    """Generate default analysis operations from metadata."""

    @staticmethod
    def plan(metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate a default tab plan from dataset metadata.

        Strategy:
        1. Frequency for each demographic variable
        2. Crosstab key variables × primary demographic
        3. NPS if detected
        4. Top/Bottom Box for scale variables
        """
        variables = metadata.get("variables", [])
        if not variables:
            return []

        # Classify variables
        demographics = []
        scales = []
        nps_vars = []
        categoricals = []

        for v in variables:
            name_lower = v["name"].lower()
            label_lower = (v.get("label") or "").lower()
            combined = name_lower + " " + label_lower

            if any(kw in combined for kw in NPS_KEYWORDS):
                nps_vars.append(v)
            elif any(kw in combined for kw in DEMO_KEYWORDS):
                demographics.append(v)
            elif v.get("type") == "numeric" and v.get("value_labels"):
                vl = v["value_labels"]
                n_labels = len(vl) if isinstance(vl, dict) else 0
                if 3 <= n_labels <= 10:
                    scales.append(v)
                elif n_labels > 0:
                    categoricals.append(v)
            elif v.get("value_labels"):
                categoricals.append(v)

        # Also check auto_detect for groupings
        auto_detect = metadata.get("auto_detect") or {}

        operations: list[dict[str, Any]] = []
        weight = None

        # Detect weight
        detected_weights = metadata.get("detected_weights", [])
        if detected_weights:
            weight = detected_weights[0]

        # 1. Frequency for demographics (max 3)
        for demo in demographics[:3]:
            operations.append({
                "type": "frequency",
                "variable": demo["name"],
                "weight": weight,
            })

        # 2. NPS if detected
        for nps_var in nps_vars[:1]:
            operations.append({
                "type": "nps",
                "variable": nps_var["name"],
                "weight": weight,
            })

        # 3. Top/Bottom Box for scales (max 5)
        for scale in scales[:5]:
            operations.append({
                "type": "top_bottom_box",
                "variable": scale["name"],
                "weight": weight,
                "params": {},  # auto-detect endpoints
            })

        # 4. Crosstab key categoricals × primary demographic (max 5)
        primary_demo = demographics[0]["name"] if demographics else None
        if primary_demo:
            for cat in (categoricals + scales)[:5]:
                if cat["name"] != primary_demo:
                    operations.append({
                        "type": "crosstab",
                        "variable": cat["name"],
                        "cross_variable": primary_demo,
                        "weight": weight,
                        "params": {"significance_level": 0.95},
                    })

        # 5. Frequency for remaining categoricals not yet covered (max 3)
        covered = {op["variable"] for op in operations}
        for cat in categoricals[:3]:
            if cat["name"] not in covered:
                operations.append({
                    "type": "frequency",
                    "variable": cat["name"],
                    "weight": weight,
                })

        logger.info("Auto-planner generated %d operations", len(operations))
        return operations
