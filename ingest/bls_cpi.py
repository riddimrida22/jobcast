"""Pull CPI-U annual index values from the BLS public API. Small and keyless-friendly."""

import os
from typing import Dict
from . import sources
from .common import bls_series, bls_annual_values


def fetch_cpi(base_year: int) -> Dict[str, object]:
    """Return the CPI block for the snapshot: the annual index for base_year and
    base_year - 5, used to deflate the five-year wage change."""
    key = os.environ.get("JOBCAST_BLS_KEY")
    resp = bls_series([sources.BLS_CPI["series"]], base_year - 5, base_year,
                      api_key=key, annual_average=True)
    values = bls_annual_values(resp).get(sources.BLS_CPI["series"], {})
    index = {str(y): round(values[str(y)], 3) for y in (base_year - 5, base_year)
             if str(y) in values}
    return {
        "note": f"CPI-U annual index (series {sources.BLS_CPI['series']}), from the BLS public API.",
        "index": index,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_cpi(2024), indent=2))
