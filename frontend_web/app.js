Auth.requireAuth();

const user = Auth.getUser();
document.getElementById("user-email").textContent = user ? user.email : "";

let savedJobIds = new Set();
let currentResults = []; // holds the last /match response so onclick handlers can reference results by index instead of embedding raw data in HTML attributes
let currentHistory = []; // same pattern for the saved-matches history list

const SENIORITY_LABELS = {
  intern: "Intern", entry: "Entry", mid: "Mid",
  senior: "Senior", staff: "Staff", principal: "Principal",
};

function scoreClass(score) {
  if (score >= 0.7) return "high";
  if (score >= 0.45) return "mid";
  return "low";
}

async function loadCompanyOptions() {
  try {
    const resp = await authFetch("/jobs/companies");
    if (!resp.ok) return;
    const data = await resp.json();
    const select = document.getElementById("filter-company");
    for (const company of data.companies || []) {
      const opt = document.createElement("option");
      opt.value = company;
      opt.textContent = company;
      select.appendChild(opt);
    }
  } catch (err) {
    // Non-critical — the dropdown just stays at "Any" if this fails.
  }
}

function resetFilters() {
  document.getElementById("filter-sort").value = "best_match";
  document.getElementById("filter-company").value = "";
  document.getElementById("filter-seniority").value = "";
  document.getElementById("filter-location").value = "";
  document.getElementById("filter-remote").checked = false;
  document.getElementById("filter-min-score").value = 0;
  document.getElementById("filter-min-score-value").textContent = "0%";
}

function renderJobCard(result, index) {
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

  // Job description shown collapsed by default (<details>/<summary>) so long
  // postings don't dominate the card. `job.description` now carries real HTML
  // formatting (paragraphs, headers, bullet lists) from the source posting — it
  // goes through DOMPurify before ever touching innerHTML, allowing only a small
  // safe tag list and stripping everything else (scripts, event handlers, styles,
  // etc.), so this can't become an XSS vector even though the content originates
  // from third-party job postings we don't control.
  const descriptionHtml = job.description
    ? `<details class="description-toggle">
         <summary>Full job description</summary>
         <div class="description-box">${sanitizeDescription(job.description)}</div>
       </details>`
    : "";

  return `
    <div class="job-card" data-job-id="${escapeHtml(job.id)}">
      <div class="job-card-head">
        <div>
          <div class="job-title">${escapeHtml(job.title)} — ${escapeHtml(job.company)}</div>
          <div class="job-meta">${escapeHtml(job.location || "")}${job.location ? " · " : ""}${escapeHtml(SENIORITY_LABELS[result.job_seniority] || result.job_seniority)}</div>
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
      ${descriptionHtml}

      <div class="job-card-actions">
        ${urlHtml}
        <button class="btn-save ${isSaved ? "saved" : ""}" onclick="toggleSave(this, ${index})">
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

// Allowlist-based sanitization for job description HTML. DOMPurify strips anything
// not on this list — scripts, event handlers (onclick etc.), styles, iframes, forms,
// everything — regardless of what the source posting contained. If DOMPurify somehow
// isn't loaded (CDN blocked, offline), fall back to fully escaping the text instead
// of ever inserting unsanitized HTML — failing closed, not open.
function sanitizeDescription(html) {
  if (typeof DOMPurify === "undefined") {
    return escapeHtml(html);
  }
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "br", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                   "strong", "b", "em", "i", "a", "span"],
    ALLOWED_ATTR: ["href"],
    ALLOW_DATA_ATTR: false,
  });
}

async function handlePdfUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const statusEl = document.getElementById("pdf-upload-status");
  statusEl.textContent = "Extracting text from PDF…";
  statusEl.className = "pdf-upload-status";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const resp = await authFetch("/resume/extract-text", {
      method: "POST",
      body: formData,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Couldn't extract text from that PDF.");

    document.getElementById("resume-input").value = data.text;
    statusEl.textContent = `Extracted text from ${file.name} — review it below before matching.`;
    statusEl.className = "pdf-upload-status success";
  } catch (err) {
    statusEl.textContent = "Error: " + err.message;
    statusEl.className = "pdf-upload-status error";
  } finally {
    event.target.value = ""; // allow re-selecting the same file if they try again
  }
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
    const sortBy = document.getElementById("filter-sort").value;
    const company = document.getElementById("filter-company").value;
    const seniority = document.getElementById("filter-seniority").value;
    const location = document.getElementById("filter-location").value.trim();
    const remoteOnly = document.getElementById("filter-remote").checked;
    const minScorePercent = parseInt(document.getElementById("filter-min-score").value, 10);

    const resp = await authFetch("/match", {
      method: "POST",
      body: JSON.stringify({
        resume_text: resumeText,
        top_k: 10,
        explain: explain,
        sort_by: sortBy,
        company: company || null,
        seniority: seniority || null,
        location: location || null,
        remote_only: remoteOnly,
        min_score: minScorePercent / 100,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(function () { return {}; });
      throw new Error(err.detail || "Request failed.");
    }
    const results = await resp.json();
    currentResults = results;

    if (results.length === 0) {
      resultsList.innerHTML = `<div class="empty-state">No matches found. Try loosening your filters (min score, location, or level) and search again.</div>`;
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

async function toggleSave(btnEl, index) {
  const result = currentResults[index];
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
    currentHistory = history;
    savedJobIds = new Set(history.map(function (h) { return h.job_id; }));
    updateSavedCount();

    const listEl = document.getElementById("history-list");
    if (history.length === 0) {
      listEl.innerHTML = `<div class="empty-state">No saved matches yet.</div>`;
      return;
    }
    listEl.innerHTML = history.map(function (h, idx) {
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
          <button class="btn-save saved" onclick="removeSaved(this, ${idx})">★ Saved</button>
        </div>
      </div>
    `;
    }).join("");
  } catch (err) {
    // authFetch already handles 401 redirects; ignore other transient errors here
  }
}

async function removeSaved(btnEl, index) {
  const jobId = currentHistory[index].job_id;
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

// Load saved-match ids and available filter options on page load.
loadHistory();
loadCompanyOptions();

// --- Embedding space visualization ---

const CLUSTER_COLORS = [
  "#5EEAD4", // mint (accent)
  "#8B93F8", // indigo
  "#FBBF24", // amber
  "#F472B6", // pink
  "#38BDF8", // sky
  "#A78BFA", // violet
  "#FB923C", // orange
  "#34D399", // green
];

async function showEmbeddingSpace() {
  const resumeText = document.getElementById("resume-input").value.trim();
  const container = document.getElementById("viz-container");
  const btn = document.getElementById("viz-btn");

  if (!resumeText) {
    container.innerHTML = `<div class="empty-state">Paste a resume first.</div>`;
    return;
  }

  btn.disabled = true;
  btn.textContent = "Loading…";
  container.innerHTML = `<div class="loading-state">Projecting embeddings to 2D and clustering…</div>`;

  try {
    const resp = await authFetch("/embedding-space", {
      method: "POST",
      body: JSON.stringify({ resume_text: resumeText, max_jobs: 300, num_clusters: 6 }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(function () { return {}; });
      throw new Error(err.detail || "Request failed.");
    }
    const data = await resp.json();
    container.innerHTML = renderEmbeddingSpaceSvg(data);
    attachVizTooltipHandlers(container);
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Error: ${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "View embedding space";
  }
}

// Native SVG <title> hover tooltips are unreliable in Safari (WebKit has long-standing
// bugs where they simply never appear, or take an unusably long delay) — so this is a
// real custom tooltip instead, driven by JS mouse events and a single reused div. Works
// consistently across browsers and lets the tooltip match the rest of the UI's styling.
function attachVizTooltipHandlers(container) {
  const svg = container.querySelector(".embedding-svg");
  if (!svg) return;

  let tooltip = document.getElementById("viz-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "viz-tooltip";
    tooltip.className = "viz-tooltip";
    document.body.appendChild(tooltip);
  }

  svg.addEventListener("mousemove", (e) => {
    const target = e.target.closest("circle[data-tooltip]");
    if (!target) {
      tooltip.style.display = "none";
      return;
    }
    tooltip.textContent = target.getAttribute("data-tooltip");
    tooltip.style.display = "block";
    tooltip.style.left = e.clientX + 14 + "px";
    tooltip.style.top = e.clientY + 14 + "px";
  });

  svg.addEventListener("mouseleave", () => {
    tooltip.style.display = "none";
  });
}

function renderEmbeddingSpaceSvg(data) {
  if (!data.points || data.points.length === 0) {
    return `<div class="empty-state">No jobs available to plot.</div>`;
  }

  const allX = data.points.map((p) => p.x).concat([data.resume_x]);
  const allY = data.points.map((p) => p.y).concat([data.resume_y]);
  const minX = Math.min(...allX), maxX = Math.max(...allX);
  const minY = Math.min(...allY), maxY = Math.max(...allY);

  const width = 700, height = 440, padding = 32;
  const rangeX = (maxX - minX) || 1; // guard against a degenerate zero-range axis
  const rangeY = (maxY - minY) || 1;

  const toSvgX = (x) => padding + ((x - minX) / rangeX) * (width - 2 * padding);
  const toSvgY = (y) => height - padding - ((y - minY) / rangeY) * (height - 2 * padding); // flip so higher values plot upward

  const circles = data.points.map((p) => {
    const color = CLUSTER_COLORS[p.cluster % CLUSTER_COLORS.length];
    const cx = toSvgX(p.x).toFixed(1);
    const cy = toSvgY(p.y).toFixed(1);
    const tooltipText = `${p.title} — ${p.company} (${Math.round(p.final_score * 100)}% fit)`;
    return `<circle cx="${cx}" cy="${cy}" r="5" fill="${color}" fill-opacity="0.8" stroke="${color}" stroke-width="1" data-tooltip="${escapeHtml(tooltipText)}"></circle>`;
  }).join("");

  const rx = toSvgX(data.resume_x).toFixed(1);
  const ry = toSvgY(data.resume_y).toFixed(1);
  const resumeMarker = `
    <circle cx="${rx}" cy="${ry}" r="10" fill="none" stroke="#ECEFF4" stroke-width="2" data-tooltip="Your resume"></circle>
    <circle cx="${rx}" cy="${ry}" r="3.5" fill="#ECEFF4" data-tooltip="Your resume"></circle>
  `;

  // "Cluster 1/2/3..." on its own means nothing — it's just an arbitrary numeric ID
  // k-means assigns, with no inherent meaning until you know what's actually in it.
  // Showing a couple of example titles from each cluster turns that opaque number
  // into something you can actually read.
  const clusters = {};
  for (const p of data.points) {
    if (!clusters[p.cluster]) clusters[p.cluster] = [];
    clusters[p.cluster].push(p.title);
  }
  const legendItems = Array.from({ length: data.num_clusters }, (_, i) => {
    const titlesInCluster = clusters[i] || [];
    const examples = [...new Set(titlesInCluster)].slice(0, 2).join(", ") || "no jobs";
    return `<span class="viz-legend-item">
      <span class="viz-legend-swatch" style="background:${CLUSTER_COLORS[i % CLUSTER_COLORS.length]}"></span>
      Cluster ${i + 1} (${titlesInCluster.length}): <span class="viz-legend-examples">${escapeHtml(examples)}${titlesInCluster.length > 2 ? ", …" : ""}</span>
    </span>`;
  }).join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" class="embedding-svg" xmlns="http://www.w3.org/2000/svg">
      ${circles}
      ${resumeMarker}
    </svg>
    <div class="viz-legend">
      <span class="viz-legend-item"><span class="viz-legend-swatch viz-legend-swatch-resume"></span>Your resume</span>
      ${legendItems}
    </div>
    <div class="viz-footnote">
      Showing ${data.jobs_shown} of ${data.total_jobs_in_index} jobs in the index. Hover a point for details.
      Axes are unitless (principal components, not a real measurement) — distance between points is what matters, not direction.
    </div>
  `;
}