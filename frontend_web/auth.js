const API_BASE = ""; // same-origin, backend serves this frontend directly

const Auth = {
  getToken() {
    return localStorage.getItem("jm_token");
  },
  getUser() {
    const raw = localStorage.getItem("jm_user");
    return raw ? JSON.parse(raw) : null;
  },
  setSession(token, user) {
    localStorage.setItem("jm_token", token);
    localStorage.setItem("jm_user", JSON.stringify(user));
  },
  clearSession() {
    localStorage.removeItem("jm_token");
    localStorage.removeItem("jm_user");
  },
  isLoggedIn() {
    return !!this.getToken();
  },
  /** Redirect to login if not authenticated. Call at the top of protected pages. */
  requireAuth() {
    if (!this.isLoggedIn()) {
      window.location.href = "/index.html";
    }
  },
  /** Redirect away from the login page if already authenticated. */
  redirectIfLoggedIn() {
    if (this.isLoggedIn()) {
      window.location.href = "/app.html";
    }
  },
  logout() {
    this.clearSession();
    window.location.href = "/index.html";
  },
};

/** Fetch wrapper that attaches the auth header and handles 401s uniformly. */
async function authFetch(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  const token = Auth.getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(API_BASE + path, { ...options, headers });

  if (resp.status === 401) {
    Auth.logout();
    throw new Error("Session expired. Please log in again.");
  }
  return resp;
}
