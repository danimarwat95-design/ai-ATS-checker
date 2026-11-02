"""
ATS Resume Checker
Upload a resume (PDF / DOCX / TXT) -> get an ATS score and improvement tips.
UI: Streamlit | AI: Google Gemini Flash
"""

import io
import json
import os
import re

import streamlit as st
from docx import Document
from pypdf import PdfReader

DEFAULT_MODEL = "gemini-2.5-flash"
MODEL_OPTIONS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"]
MAX_RESUME_CHARS = 30000
MAX_JD_CHARS = 8000
MIN_TEXT_CHARS = 150

BREAKDOWN_LABELS = {
    "formatting": "Formatting & Structure",
    "keywords": "Keywords",
    "content_quality": "Content Quality",
    "experience_impact": "Experience & Impact",
    "skills_relevance": "Skills Relevance",
    "readability": "Readability",
}


# --------------------------------------------------------------------------
# 1. Text extraction
# --------------------------------------------------------------------------
def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from a PDF, DOCX or TXT file."""
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password protected.")
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(pages)

    elif name.endswith(".docx"):
        doc = Document(io.BytesIO(file_bytes))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        text = "\n".join(parts)

    elif name.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="ignore")

    else:
        raise ValueError("Unsupported file type. Please upload PDF, DOCX or TXT.")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------
# 2. Quick rule-based checks (no AI needed)
# --------------------------------------------------------------------------
SECTION_PATTERNS = {
    "Summary / Objective": r"\b(summary|objective|profile|about me)\b",
    "Experience": r"\b(experience|employment|work history|internship)\b",
    "Education": r"\b(education|academic|qualification)\b",
    "Skills": r"\b(skills|technologies|technical skills|competencies)\b",
    "Projects": r"\b(projects|portfolio)\b",
    "Certifications": r"\b(certifications?|certificates?|courses|training)\b",
}


def local_checks(text: str) -> dict:
    """Simple rule-based checks that complement the AI analysis."""
    lower = text.lower()
    words = re.findall(r"\b\w+\b", text)
    return {
        "word_count": len(words),
        "has_email": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)),
        "has_phone": bool(re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)),
        "has_linkedin": "linkedin.com" in lower,
        "has_numbers": len(re.findall(r"\d+%|\$\s?\d+|\b\d{2,}\b", text)) >= 3,
        "sections": {
            name: bool(re.search(pat, lower)) for name, pat in SECTION_PATTERNS.items()
        },
    }


# --------------------------------------------------------------------------
# 3. Gemini call
# --------------------------------------------------------------------------
PROMPT_TEMPLATE = """You are an expert ATS (Applicant Tracking System) analyst and professional resume coach.

Analyse the resume below{jd_clause} and respond with ONLY a valid JSON object (no markdown, no commentary) using exactly this structure:

{{
  "overall_score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "breakdown": {{
    "formatting": <integer 0-100>,
    "keywords": <integer 0-100>,
    "content_quality": <integer 0-100>,
    "experience_impact": <integer 0-100>,
    "skills_relevance": <integer 0-100>,
    "readability": <integer 0-100>
  }},
  "strengths": ["<short point>", "..."],
  "weaknesses": ["<short point>", "..."],
  "missing_keywords": ["<keyword>", "..."],
  "improvements": [
    {{"section": "<resume section>", "issue": "<what is wrong>", "suggestion": "<how to fix it>", "example": "<short example text>"}}
  ],
  "rewritten_bullets": [
    {{"original": "<weak bullet taken from the resume>", "improved": "<stronger, quantified version>"}}
  ]
}}

Scoring rules:
- Be realistic and strict. Average resumes score 55-70. Only excellent ones exceed 85.
- Judge: ATS-friendly structure and standard section headings, keyword coverage, action verbs, quantified achievements, clarity, grammar, length, and contact details.
{jd_rules}- Give 4-6 strengths, 4-6 weaknesses, 5-10 improvements, up to 12 missing keywords and 3-5 rewritten bullets.
- Never invent experience the candidate does not have. Rewritten bullets may use placeholders like [X%] where numbers are unknown.

{jd_block}RESUME:
\"\"\"
{resume}
\"\"\"
"""


def build_prompt(resume_text: str, job_description: str = "") -> str:
    jd = (job_description or "").strip()
    if jd:
        jd_clause = " against the job description"
        jd_rules = (
            "- Score keyword and skills relevance against the job description. "
            "'missing_keywords' must list important terms from the job description absent from the resume.\n"
        )
        jd_block = f'JOB DESCRIPTION:\n"""\n{jd[:MAX_JD_CHARS]}\n"""\n\n'
    else:
        jd_clause = ""
        jd_rules = (
            "- No job description is given, so judge general ATS quality and list commonly "
            "expected keywords for the candidate's apparent field in 'missing_keywords'.\n"
        )
        jd_block = ""
    return PROMPT_TEMPLATE.format(
        jd_clause=jd_clause,
        jd_rules=jd_rules,
        jd_block=jd_block,
        resume=resume_text[:MAX_RESUME_CHARS],
    )


def parse_json(raw: str) -> dict:
    """Parse JSON from a model reply, tolerating code fences or extra text."""
    if not raw:
        raise ValueError("Empty response from the model.")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise ValueError("The model did not return valid JSON.")


def _clamp(value, default=0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _str_list(value) -> list:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def normalize_result(data: dict) -> dict:
    """Make sure every field exists and has the right type."""
    if not isinstance(data, dict):
        raise ValueError("Unexpected response format.")
    breakdown_in = data.get("breakdown") if isinstance(data.get("breakdown"), dict) else {}
    breakdown = {k: _clamp(breakdown_in.get(k)) for k in BREAKDOWN_LABELS}

    overall = data.get("overall_score")
    if overall is None and breakdown:
        overall = sum(breakdown.values()) / len(breakdown)

    improvements = []
    for item in data.get("improvements") or []:
        if isinstance(item, dict):
            improvements.append(
                {
                    "section": str(item.get("section", "General")),
                    "issue": str(item.get("issue", "")),
                    "suggestion": str(item.get("suggestion", "")),
                    "example": str(item.get("example", "")),
                }
            )

    bullets = []
    for item in data.get("rewritten_bullets") or []:
        if isinstance(item, dict):
            bullets.append(
                {
                    "original": str(item.get("original", "")),
                    "improved": str(item.get("improved", "")),
                }
            )

    return {
        "overall_score": _clamp(overall),
        "summary": str(data.get("summary", "")),
        "breakdown": breakdown,
        "strengths": _str_list(data.get("strengths")),
        "weaknesses": _str_list(data.get("weaknesses")),
        "missing_keywords": _str_list(data.get("missing_keywords")),
        "improvements": improvements,
        "rewritten_bullets": bullets,
    }


def analyze_resume(api_key: str, model: str, resume_text: str, job_description: str = "") -> dict:
    """Send the resume to Gemini and return a normalised result dict."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(resume_text, job_description)
    config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json",
    )

    last_error = None
    for _ in range(2):  # one retry if the JSON is broken
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        try:
            return normalize_result(parse_json(response.text))
        except ValueError as err:
            last_error = err
    raise ValueError(f"Could not read the AI response: {last_error}")


# --------------------------------------------------------------------------
# 4. Report text (for download)
# --------------------------------------------------------------------------
def build_report(result: dict) -> str:
    lines = [f"ATS SCORE: {result['overall_score']}/100", "", result["summary"], ""]
    lines.append("SCORE BREAKDOWN")
    for key, label in BREAKDOWN_LABELS.items():
        lines.append(f"- {label}: {result['breakdown'][key]}/100")
    for title, key in [
        ("STRENGTHS", "strengths"),
        ("WEAKNESSES", "weaknesses"),
        ("MISSING KEYWORDS", "missing_keywords"),
    ]:
        lines += ["", title] + [f"- {x}" for x in result[key]]
    lines += ["", "IMPROVEMENTS"]
    for i, imp in enumerate(result["improvements"], 1):
        lines.append(f"{i}. [{imp['section']}] {imp['issue']}")
        lines.append(f"   Fix: {imp['suggestion']}")
        if imp["example"]:
            lines.append(f"   Example: {imp['example']}")
    lines += ["", "REWRITTEN BULLETS"]
    for b in result["rewritten_bullets"]:
        lines.append(f"- Before: {b['original']}")
        lines.append(f"  After:  {b['improved']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 5. Streamlit UI
# --------------------------------------------------------------------------
def get_api_key() -> str:
    """Look for the key in Streamlit secrets, then environment variables."""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def score_label(score: int) -> str:
    if score >= 80:
        return "Excellent"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Needs work"
    return "Weak"


def show_results(result: dict, checks: dict) -> None:
    score = result["overall_score"]

    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("ATS Score", f"{score}/100", score_label(score))
        st.progress(score / 100)
    with col2:
        st.write(result["summary"])

    tab_overview, tab_improve, tab_keywords, tab_bullets, tab_checks = st.tabs(
        ["Overview", "Improvements", "Keywords", "Rewritten bullets", "Quick checks"]
    )

    with tab_overview:
        st.subheader("Score breakdown")
        for key, label in BREAKDOWN_LABELS.items():
            val = result["breakdown"][key]
            st.write(f"**{label}** - {val}/100")
            st.progress(val / 100)
        left, right = st.columns(2)
        with left:
            st.subheader("Strengths")
            for s in result["strengths"] or ["No strengths returned."]:
                st.markdown(f"- {s}")
        with right:
            st.subheader("Weaknesses")
            for w in result["weaknesses"] or ["No weaknesses returned."]:
                st.markdown(f"- {w}")

    with tab_improve:
        if not result["improvements"]:
            st.info("No improvements returned.")
        for i, imp in enumerate(result["improvements"], 1):
            with st.expander(f"{i}. {imp['section']}: {imp['issue'][:80]}", expanded=i <= 3):
                st.markdown(f"**Issue:** {imp['issue']}")
                st.markdown(f"**How to fix:** {imp['suggestion']}")
                if imp["example"]:
                    st.markdown(f"**Example:** _{imp['example']}_")

    with tab_keywords:
        st.subheader("Missing keywords")
        if result["missing_keywords"]:
            st.write(", ".join(f"`{k}`" for k in result["missing_keywords"]))
        else:
            st.success("No important keywords missing.")

    with tab_bullets:
        if not result["rewritten_bullets"]:
            st.info("No rewritten bullets returned.")
        for b in result["rewritten_bullets"]:
            st.markdown(f"**Before:** {b['original']}")
            st.markdown(f"**After:** {b['improved']}")
            st.divider()

    with tab_checks:
        st.write(f"**Word count:** {checks['word_count']} (ideal: 400-800)")
        rows = {
            "Email found": checks["has_email"],
            "Phone found": checks["has_phone"],
            "LinkedIn link": checks["has_linkedin"],
            "Quantified achievements (numbers/%)": checks["has_numbers"],
        }
        rows.update({f"Section: {k}": v for k, v in checks["sections"].items()})
        for label, ok in rows.items():
            st.write(("✅ " if ok else "❌ ") + label)

    st.download_button(
        "Download report (.txt)",
        data=build_report(result),
        file_name="ats_report.txt",
        mime="text/plain",
    )


def main() -> None:
    st.set_page_config(page_title="ATS Resume Checker", page_icon="📄", layout="wide")
    st.title("📄 ATS Resume Checker")
    st.caption("Upload your resume to get an ATS score and tips to improve it.")

    with st.sidebar:
        st.header("Settings")
        api_key = get_api_key()
        if api_key:
            st.success("API key loaded.")
        else:
            api_key = st.text_input("Gemini API key", type="password",
                                    help="Get a free key at https://aistudio.google.com/apikey")
        model = st.selectbox("Gemini model", MODEL_OPTIONS, index=0)
        st.caption("Your resume is sent to Google's Gemini API for analysis.")

    uploaded = st.file_uploader("Upload resume", type=["pdf", "docx", "txt"])
    job_description = st.text_area(
        "Job description (optional, for a tailored score)",
        height=150,
        placeholder="Paste the job description here...",
    )

    if st.button("Analyze resume", type="primary"):
        if uploaded is None:
            st.warning("Please upload a resume first.")
            return
        if not api_key:
            st.warning("Please enter your Gemini API key in the sidebar.")
            return

        try:
            text = extract_text(uploaded.getvalue(), uploaded.name)
        except Exception as err:
            st.error(f"Could not read the file: {err}")
            return

        if len(text) < MIN_TEXT_CHARS:
            st.error(
                "Very little text was found. If this is a scanned/image PDF, ATS systems "
                "cannot read it either. Export a text-based PDF or upload a DOCX."
            )
            return

        try:
            with st.spinner("Analyzing your resume..."):
                result = analyze_resume(api_key, model, text, job_description)
        except Exception as err:
            st.error(f"Analysis failed: {err}")
            return

        show_results(result, local_checks(text))


if __name__ == "__main__":
    main()
