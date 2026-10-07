"""Transparent v1 baseline. No hiring decisions or inferred sensitive attributes."""
import re

ALIASES = {
    "python": ["python"], "javascript": ["javascript", "js"], "typescript": ["typescript", "ts"],
    "java": ["java"], "c++": ["c++", "cpp"], "c": ["c"], "c#": ["c#", "csharp"],
    "react": ["react", "reactjs", "react.js"], "node.js": ["node.js", "nodejs"],
    "sql": ["sql", "postgresql", "mysql", "sqlite"], "excel": ["excel", "microsoft excel"],
    "power bi": ["power bi", "powerbi"], "selenium": ["selenium"], "testing": ["testing", "quality assurance"],
    "automation": ["automation", "automated"], "customer support": ["customer support", "customer service"],
    "communication": ["communication"], "sales": ["sales"], "accounting": ["accounting", "bookkeeping"],
    "git": ["git"], "aws": ["aws", "amazon web services"], "docker": ["docker"],
    'html':['html','html5'], 'css':['css','css3'], 'kubernetes':['kubernetes','k8s'],
    'machine learning':['machine learning'], 'pandas':['pandas'], 'data analysis':['data analysis','data analytics'],
    'tally':['tally','tallyprime','tally erp'], 'gst':['gst','goods and services tax'],
    'accounts payable':['accounts payable'], 'accounts receivable':['accounts receivable'],
    'bank reconciliation':['bank reconciliation'], 'financial reporting':['financial reporting'],
    'recruitment':['recruitment','recruiting','talent acquisition'], 'payroll':['payroll'],
    'crm':['crm','customer relationship management'], 'lead generation':['lead generation','prospecting'],
    'b2b sales':['b2b sales','business to business sales'], 'seo':['seo','search engine optimization'],
    'digital marketing':['digital marketing'], 'autocad':['autocad'], 'solidworks':['solidworks'],
    'inventory management':['inventory management','inventory control'], 'supply chain':['supply chain'],
}
GENERIC_SKILLS = {'communication','teamwork','problem solving','leadership','time management','microsoft office'}


def mentions(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<![\w+#])" + re.escape(phrase.lower()) + r"(?![\w+#])", text.lower()))


def evidence(text: str, skill: str) -> str | None:
    # A skill list is evidence of a claim, not proof of proficiency.
    aliases = ALIASES.get(skill.lower(), [skill.lower()])
    for line in text.splitlines():
        if any(mentions(line, alias) for alias in aliases):
            if any(re.search(r"\b(no|without|lack|lacking|not(?!\s+(?:only|just)\b))\b.{0,25}" + re.escape(alias), line, re.I) for alias in aliases):
                continue
            return line.strip()[:240]
    return None


def match_jobs(resume: str, preferences: dict, jobs: list[dict]) -> list[dict]:
    results = []
    evidence_cache = {}
    for job in jobs:
        arrangement = preferences.get("work_arrangement", "any")
        if arrangement != "any" and job.get("work_arrangement") != arrangement:
            continue
        location = preferences.get("location", "").strip().lower()
        if location and job.get("work_arrangement") != "remote" and location not in job.get("location", "").lower():
            continue
        skills = list(dict.fromkeys(str(s).strip().lower() for s in job.get("skills", []) if str(s).strip()))
        for skill in skills:
            if skill not in evidence_cache: evidence_cache[skill] = evidence(resume,skill)
        found = {s: evidence_cache[s] for s in skills}
        matched = [s for s in skills if found[s]]
        missing = [s for s in skills if not found[s]]
        minimum = job.get("minimum_experience_years")
        years = preferences.get("experience_years")
        experience_gap = minimum is not None and years is not None and years < minimum
        weights = {skill: .2 if skill in GENERIC_SKILLS else 1 for skill in skills}
        coverage = sum(weights[skill] for skill in matched) / sum(weights.values()) if skills else 0
        # Never fill recommendations with unrelated jobs just to reach a count.
        if not matched:
            continue
        score = round(coverage * 100)
        specific = any(skill not in GENERIC_SKILLS for skill in matched)
        strong = coverage >= .8 and specific and not experience_gap and not (minimum is not None and years is None)
        band = "Strong match" if strong else ("Related role" if coverage >= .5 and not experience_gap else "Stretch role")
        notes = []
        if not specific:
            band = 'Stretch role'; score = min(score,25)
            notes.append('Only general skills overlap; role-specific experience needs confirmation')
        if minimum is not None and years is None:
            notes.append("Experience requirement needs confirmation")
        if experience_gap:
            notes.append(f"Role requests at least {minimum:g} years; you entered {years:g}")
        results.append({"job": job, "score": score, "band": band, "matched_skills": matched,
                        "missing_skills": missing, "evidence": {s: found[s] for s in matched},
                        "notes": notes, "algorithm_version": "skills-evidence-v2",
                        "limitation": "Resume evidence is self-reported. Fit is not a selection probability."})
    return sorted(results, key=lambda result: (-result["score"], result["job"]["id"]))
