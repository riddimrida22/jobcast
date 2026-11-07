"""Read an uploaded resume (PDF / Word / text) and map it to the closest standard
occupation, plus extract skills, experience, and education, to auto-fill the form.

Processed in memory only; the file is never stored. The extraction is a transparent
heuristic; when an API key is configured it can be upgraded to a language-model parse
(extraction only, never scoring).
"""

import io
import re
import zipfile
import html
from typing import Dict, Any, List, Optional

FIELD_KEYWORDS = [
    ("Law", ["juris doctor", " jd ", "law school", "llb", "paralegal", "attorney"]),
    ("Finance or Accounting", ["finance", "accounting", "cpa", "cfa", "audit"]),
    ("Economics", ["economics", "econometrics"]),
    ("Engineering", ["engineering", "mechanical", "civil engineer", "electrical engineer"]),
    ("Computer Science or IT", ["computer science", "information technology", "software engineering", " b.s. cs"]),
    ("Business or Management", ["business administration", "mba", "management", "marketing"]),
    ("Healthcare or Medicine", ["nursing", "medicine", "medical", "pharmacy", "registered nurse"]),
    ("Life Sciences", ["biology", "biochemistry", "molecular", "life sciences"]),
    ("Physical Sciences or Math", ["physics", "chemistry", "mathematics", "statistics"]),
    ("Social Sciences", ["psychology", "sociology", "political science", "anthropology"]),
    ("Education", ["education", "teaching", "pedagogy"]),
    ("Arts or Humanities", ["history", "literature", "philosophy", "fine arts", "english"]),
    ("Communications or Media", ["communications", "journalism", "media studies"]),
]

SKILL_HEADINGS = ["technical skills", "core competencies", "skills & abilities", "key skills", "skills"]


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<[^>]+>", " ", xml)
            return html.unescape(re.sub(r"[ \t]+", " ", xml))
        except Exception:
            return ""
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            return ""
    # txt or unknown
    return data.decode("utf-8", "replace")


def _match_occupation(text: str, snapshot) -> Optional[str]:
    # Resumes put the job title near the top: run the engine's fuzzy matcher on those lines.
    lines = [ln.strip(" \t-•") for ln in text.splitlines() if ln.strip()]
    for ln in lines[:8]:
        if 3 <= len(ln) <= 55 and not ln.lower().startswith(("summary", "objective", "experience", "education", "skills")):
            occ = snapshot.match_title(ln)
            if occ:
                return occ["title"]
    # Fallback: exact alias substring anywhere in the resume.
    low = text.lower()
    best_soc, best_score = None, 0.0
    for alias, soc, is_primary in snapshot._alias_index:
        if len(alias) < 6 or alias not in low:
            continue
        score = len(alias) + (25 if is_primary else 0)
        if score > best_score:
            best_score, best_soc = score, soc
    return snapshot._occ_by_soc[best_soc]["title"] if best_soc else None


def _extract_skills(text: str) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    low = [ln.lower() for ln in lines]
    for i, ln in enumerate(low):
        head = ln.rstrip(":").strip()
        if head in SKILL_HEADINGS or any(ln.startswith(h) for h in SKILL_HEADINGS):
            blob = lines[i]
            # the heading line itself may hold the skills after a colon, plus next 2 lines
            blob = re.sub(r"(?i)^.*?(skills|competencies|abilities)\s*:?", "", blob)
            for j in range(i + 1, min(i + 4, len(lines))):
                if not lines[j]:
                    break
                blob += " , " + lines[j]
            parts = re.split(r"[,;|•·\t]+", blob)
            skills = [p.strip() for p in parts if 1 < len(p.strip()) < 40]
            if skills:
                return skills[:15]
    return []


def parse_resume(text: str, snapshot) -> Dict[str, Any]:
    low = text.lower()
    title = _match_occupation(text, snapshot)
    skills = _extract_skills(text)

    years = [int(m) for m in re.findall(r"(\d{1,2})\+?\s*years", low)]
    yrs = max(years) if years else None
    experience_band = None
    if yrs is not None:
        experience_band = "1" if yrs < 2 else "4" if yrs <= 5 else "8" if yrs <= 10 else "15" if yrs <= 20 else "25"

    education = None
    if re.search(r"\b(ph\.?\s?d|doctor|doctorate)\b", low):
        education = "Graduate"
    elif re.search(r"\b(master|mba|m\.?s\.?|m\.?a\.?|msc|m\.?eng)\b", low):
        education = "Graduate"
    elif re.search(r"\b(bachelor|b\.?s\.?|b\.?a\.?|bsc|b\.?eng|undergraduate)\b", low):
        education = "Bachelor"
    elif re.search(r"\bassociate('?s)?\b", low):
        education = "Associate"
    elif re.search(r"\b(high school|ged|diploma)\b", low):
        education = "High school"

    education_field = None
    for field, kws in FIELD_KEYWORDS:
        if any(k in low for k in kws):
            education_field = field
            break

    return {"title": title, "skills": skills, "experience_years": yrs,
            "experience_band": experience_band, "education": education,
            "education_field": education_field}
