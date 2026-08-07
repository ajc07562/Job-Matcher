Auth.requireAuth();

const user = Auth.getUser();
document.getElementById("user-email").textContent = user ? user.email : "";

let savedJobIds = new Set();

function scoreClass(score) {
  if (score >= 0.7) return "high";
  if (score >= 0.45) return "mid";
  return "low";
}

function renderJobCard(result) {
  const job = result.job;
  const cls = scoreClass(result.final_score);
  const isSaved = savedJobIds.has(job.id);

  const matchedChips = (result.matched_skills || [])
    .map((s) => `<span class="chip matched">${escapeHtml(s)}</span>`).join("");
  const missingChips = (result.missing_skills || [])
    .map((s) => `<span class="chip missing">${escapeHtml(s)}</span>`).join("");

  const explanationHtml = result.explanation
    ? `<div class="explanation-box">${escapeHtml(result.explanation)}</div>`
    : "";

  const urlHtml = job.url
    ? `<a href="${escapeHtml(job.url)}" target="_blank" rel="noopener">View listing →</a>`
    : "";

  return `
    <div class="job-card" data-job-id="${escapeHtml(job.id)}">
      <div class="job-card-head">
        <div>
          <div class="job-title">${escapeHtml(job.title)} — ${escapeHtml(job.company)}</div>
          <div class="job-meta">${escapeHtml(job.location || "")}</div>
        </div>
        <div class="score-badge ${cls}">${Math.round(result.final_score * 100)}%</div>
      </div>

      <div class="subscore-row">
        <span>EMBED ${result.embedding_score.toFixed(2)}</span>
        <span>SKILLS ${result.skill_overlap_score.toFixed(2)}</span>
        <span>LEVEL ${result.seniority_score.toFixed(2)}</span>
      </div>

      ${matchedChips || missingChips ? `<div class="skill-chips">${matchedChips}${missingChips}</div>` : ""}
      ${explanationHtml}

      <div class="job-card-actions">
        ${urlHtml}
        <button class="btn-save ${isSaved ? "saved" : ""}" onclick='toggleSave(this, ${JSON.stringify(result)})'>
          ${isSaved ? "★ Saved" : "☆ Save"}
        </button>
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

async function findMatches() {
  const resumeText = document.getElementById("resume-input").value.trim();
  const resultsList = document.getElementById("results-list");
  const btn = document.getElementById("find-btn");

  if (!resumeText) {
    resultsList.innerHTML = `<div class="empty-state">Paste a resume first.</div>`;
    return;
  }

  btn.disabled = true;
  btn.textContent = "Finding matches…";
  resultsList.innerHTML = `<div class="loading-state">Embedding resume, ranking jobs, generating explanations…</div>`;

  try {
    const explain = document.getElementById("explain-checkbox").checked;
    const resp = await authFetch("/match", {
      method: "POST",
      body: JSON.stringify({ resume_text: resumeText, top_k: 10, explain: explain }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(function () { return {}; });
      throw new Error(err.detail || "Request failed.");
    }
    const results = await resp.json();

    if (results.length === 0) {
      resultsList.innerHTML = `<div class="empty-state">No matches found.</div>`;
    } else {
      resultsList.innerHTML = results.map(renderJobCard).join("");
    }
  } catch (err) {
    resultsList.innerHTML = `<div class="empty-state">Error: ${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Find matches";
  }
}

async function toggleSave(btnEl, result) {
  const job = result.job;
  const isSaved = savedJobIds.has(job.id);

  try {
    if (isSaved) {
      await authFetch("/matches/" + encodeURIComponent(job.id), { method: "DELETE" });
      savedJobIds.delete(job.id);
      btnEl.textContent = "☆ Save";
      btnEl.classList.remove("saved");
    } else {
      await authFetch("/matches/save", {
        method: "POST",
        body: JSON.stringify({
          job_id: job.id,
          company: job.company,
          title: job.title,
          final_score: result.final_score,
          explanation: result.explanation || null,
          url: job.url || null,
        }),
      });
      savedJobIds.add(job.id);
      btnEl.textContent = "★ Saved";
      btnEl.classList.add("saved");
    }
    updateSavedCount();
  } catch (err) {
    alert("Couldn't update saved matches: " + err.message);
  }
}

function updateSavedCount() {
  document.getElementById("saved-count").textContent = savedJobIds.size;
}

async function loadHistory() {
  try {
    const resp = await authFetch("/matches/history");
    if (!resp.ok) return;
    const history = await resp.json();
    savedJobIds = new Set(history.map(function (h) { return h.job_id; }));
    updateSavedCount();

    const listEl = document.getElementById("history-list");
    if (history.length === 0) {
      listEl.innerHTML = `<div class="empty-state">No saved matches yet.</div>`;
      return;
    }
    listEl.innerHTML = history.map(function (h) {
      return `
      <div class="job-card">
        <div class="job-card-head">
          <div>
            <div class="job-title">${escapeHtml(h.title)} — ${escapeHtml(h.company)}</div>
          </div>
          <div class="score-badge ${scoreClass(h.final_score)}">${Math.round(h.final_score * 100)}%</div>
        </div>
        ${h.explanation ? `<div class="explanation-box">${escapeHtml(h.explanation)}</div>` : ""}
        <div class="job-card-actions">
          ${h.url ? `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener">View listing →</a>` : ""}
          <button class="btn-save saved" onclick="removeSaved(this, '${h.job_id}')">★ Saved</button>
        </div>
      </div>
    `;
    }).join("");
  } catch (err) {
    // authFetch already handles 401 redirects; ignore other transient errors here
  }
}

async function removeSaved(btnEl, jobId) {
  await authFetch("/matches/" + encodeURIComponent(jobId), { method: "DELETE" });
  savedJobIds.delete(jobId);
  updateSavedCount();
  loadHistory();
}

function toggleHistory() {
  const panel = document.getElementById("history-panel");
  const show = panel.style.display === "none";
  panel.style.display = show ? "block" : "none";
  if (show) loadHistory();
}

// Load saved-match ids on page load so "Save" buttons render correctly from the start.
loadHistory();
