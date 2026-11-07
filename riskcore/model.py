"""Input model: the facts a person enters. Protected characteristics are deliberately
absent; they must never feed the score (BUILD_PLAN.md, privacy guardrails)."""

from dataclasses import dataclass, replace
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class Profile:
    title: str
    zip_code: Optional[str] = None
    age: Optional[int] = None
    experience_years: Optional[int] = None
    education: Optional[str] = None
    education_field: Optional[str] = None   # field of study: finance, law, engineering, ...
    skills: Optional[str] = None            # comma-separated skills the user added
    union_status: Optional[str] = None  # "yes" | "no" | None
    pay_current: Optional[float] = None
    pay_5yr_ago: Optional[float] = None
    graduation_year: Optional[int] = None

    def with_overrides(self, overrides: Dict[str, Any]) -> "Profile":
        """Return a copy with some fields replaced. Used for what-if scenarios.

        Only known fields are allowed, so a what-if can never introduce an input the
        engine does not model on a defensible path.
        """
        allowed = set(self.__dataclass_fields__.keys())
        unknown = set(overrides) - allowed
        if unknown:
            raise ValueError(f"unknown what-if field(s): {sorted(unknown)}")
        return replace(self, **overrides)
