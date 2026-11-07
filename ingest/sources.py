"""Source registry for ingestion: where each dataset comes from, its version, and its
licence. Kept in one place so a new data year is a config change.

Verified reachable 2026-11-06:
- O*NET database zip downloads directly (~13.2 MB).
- The BLS website blocks scripted downloads (403, Akamai); BLS data is pulled via the
  public API instead (api.bls.gov), which works keyless at low volume.
"""

ONET = {
    "id": "onet",
    "name": "O*NET",
    "version": "29.1",
    "url": "https://www.onetcenter.org/dl_files/database/db_29_1_text.zip",
    "cache_name": "onet_db_29_1_text.zip",
    "licence": "CC BY 4.0 (attribution required)",
    "use": "Occupation titles, SOC codes, task statements, work context, job zones.",
}

BLS_CPI = {
    "id": "bls_cpi",
    "name": "BLS CPI-U",
    "series": "CUUR0000SA0",     # CPI-U, US city average, all items, not seasonally adjusted
    "api": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    "licence": "Public domain (US government).",
    "use": "Inflation index to deflate the wage-trajectory signal.",
}

BLS_OEWS = {
    "id": "bls_oews",
    "name": "BLS OEWS",
    "licence": "Public domain (US government).",
    "use": "Employment and wages by occupation and area.",
    # OEWS series via the API. Series ID format (validated at run time against a known
    # occupation before any bulk pull):
    #   OEU <area_type:1> <area_code:7> <industry:6=000000> <occupation:6> <datatype:2>
    # datatype 01 = employment, 13 = annual median wage. Area type N=national, M=metro.
    "datatype_employment": "01",
    "datatype_annual_median_wage": "13",
    "national_area": ("N", "0000000"),
    "metros": {   # CBSA codes used in the fixture and first real build
        "35620": "New York-Newark-Jersey City",
        "31080": "Los Angeles-Long Beach-Anaheim",
    },
}

# AI/robotics task exposure. Exact file URLs are confirmed when the exposure module is
# built; candidates (public):
#   - Eloundou et al. 2023, GPTs are GPTs (task-level LLM exposure), github.com/openai/GPTs-are-GPTs
#   - O*NET work-context physical/manual variables -> robotics-axis proxy
EXPOSURE = {
    "id": "exposure",
    "name": "Task exposure (AI and robotics)",
    "licence": "Per each source; Eloundou code MIT.",
    "use": "Per-task AI/software exposure and physical/robotics exposure.",
}
