from __future__ import annotations

from . import config


CALIBRATION_CASES: dict[str, tuple[dict[str, object], ...]] = {
    "tech": tuple(
        {"id": f"tech-{index:02d}", "topic": topic, "required_angles": ("mechanism", "cost", "industry", "ordinary_people")}
        for index, topic in enumerate((
            "consumer AI device", "semiconductor export rule", "open-source model", "battery factory",
            "space launch", "robot deployment", "software pricing", "privacy incident",
            "cloud infrastructure", "creator tool",
        ), 1)
    ),
    "education": tuple(
        {"id": f"education-{index:02d}", "topic": topic, "required_angles": ("affected_people", "evidence", "method", "fairness")}
        for index, topic in enumerate((
            "school policy", "college admission", "learning science", "family education", "adult learning",
            "teacher workload", "education AI", "rural access", "assessment reform", "student wellbeing",
        ), 1)
    ),
    "sports": tuple(
        {"id": f"sports-{index:02d}", "topic": topic, "required_angles": ("key_moment", "tactics", "human_performance", "practical_advice")}
        for index, topic in enumerate((
            "football match", "basketball series", "tennis final", "badminton tournament", "track event",
            "swimming meet", "esports final", "running training", "strength training", "injury prevention",
        ), 1)
    ),
}


def calibration_status() -> dict:
    return {
        category: {
            "profile": config.CATEGORIES[category].tone,
            "sample_count": len(cases),
            "case_ids": [str(case["id"]) for case in cases],
            "rubric": ("facts", "viewpoint", "category_identity", "clarity", "tone"),
            "minimum_score": 4,
        }
        for category, cases in CALIBRATION_CASES.items()
    }
