import sys
from pathlib import Path

import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import API_HOST, API_PORT, DATA_DIR  # noqa: E402

API_URL = f"http://{API_HOST}:{API_PORT}"

st.set_page_config(page_title="Job Matcher", page_icon="🎯", layout="wide")
st.title("🎯 Job Matcher")
st.caption("Semantic search + hybrid ranking over real job listings, with AI-generated fit explanations.")

with st.sidebar:
    st.header("Resume")
    use_sample = st.checkbox("Use sample resume", value=True)
    if use_sample:
        sample_path = DATA_DIR / "sample_resume.txt"
        resume_text = sample_path.read_text() if sample_path.exists() else ""
        st.text_area("Resume text", resume_text, height=300, disabled=True)
    else:
        resume_text = st.text_area("Paste your resume", height=300,
                                    placeholder="Paste your resume text here...")

    top_k = st.slider("Number of matches", min_value=3, max_value=20, value=8)
    explain = st.checkbox("Generate AI explanations (requires ANTHROPIC_API_KEY)", value=True)
    run = st.button("Find matches", type="primary", use_container_width=True)

try:
    health = requests.get(f"{API_URL}/health", timeout=3).json()
    st.sidebar.success(f"API connected — {health['jobs_indexed']} jobs indexed"
                        + (" · LLM ready" if health["llm_available"] else " · LLM not configured"))
except requests.exceptions.RequestException:
    st.sidebar.error(f"Can't reach API at {API_URL}. Start it with:\n\n"
                      "`uvicorn backend.main:app --reload --port 8000`")

if run:
    if not resume_text.strip():
        st.warning("Paste a resume or check 'Use sample resume' first.")
    else:
        with st.spinner("Embedding, ranking, and (if enabled) generating explanations..."):
            try:
                resp = requests.post(
                    f"{API_URL}/match",
                    json={"resume_text": resume_text, "top_k": top_k, "explain": explain},
                    timeout=60,
                )
                resp.raise_for_status()
                results = resp.json()
            except requests.exceptions.RequestException as e:
                st.error(f"Request failed: {e}")
                results = []

        for i, r in enumerate(results, start=1):
            job = r["job"]
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.subheader(f"{i}. {job['title']} — {job['company']}")
                    if job.get("location"):
                        st.caption(job["location"])
                with col2:
                    st.metric("Fit score", f"{r['final_score']:.2f}")

                c1, c2, c3 = st.columns(3)
                c1.caption(f"Embedding sim: {r['embedding_score']:.2f}")
                c2.caption(f"Skill overlap: {r['skill_overlap_score']:.2f}")
                c3.caption(f"Seniority fit: {r['seniority_score']:.2f}")

                if r["matched_skills"]:
                    st.write("**Matched skills:** " + ", ".join(r["matched_skills"]))
                if r["missing_skills"]:
                    st.write("**Missing skills:** " + ", ".join(r["missing_skills"]))

                if r.get("explanation"):
                    st.info(r["explanation"])

                if job.get("url"):
                    st.markdown(f"[View listing]({job['url']})")
