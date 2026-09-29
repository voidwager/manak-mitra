/**
 * HTTP client for the workbench backend.
 *
 * Single place where fetch is called. Components and context never talk to
 * the network directly - they go through services/api.js, which goes
 * through here.
 */

/**
 * Same-origin by default. In development the Vite dev server proxies /api to
 * the backend (see vite.config.js); in the planned single-container
 * deployment the backend serves the frontend, so /api is correct there too.
 *
 * Set VITE_API_BASE_URL to an absolute URL only when the API genuinely lives
 * on another origin.
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

/**
 * The session token from sign-in.
 *
 * Until Phase 16 this was an `X-User-Id` header the client simply asserted,
 * which anyone could set to anything. It is now a bearer token the server
 * verifies against a session row on every request.
 *
 * Held in memory and mirrored to localStorage so a refresh does not sign
 * you out. localStorage is readable by any script on the origin, which is
 * the standard trade for a single-page app; the mitigation is that the
 * token is revocable server-side and the app renders no untrusted HTML
 * (see components/chat/MessageContent.jsx).
 */
const TOKEN_KEY = 'synq_session_token';

let activeToken = null;

export const setActiveToken = (token) => {
  activeToken = token || null;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode - the session simply will not survive a refresh */
  }
};

export const getActiveToken = () => {
  if (activeToken) return activeToken;
  try {
    activeToken = localStorage.getItem(TOKEN_KEY);
  } catch {
    activeToken = null;
  }
  return activeToken;
};

export class ApiError extends Error {
  constructor(message, { status, url, body } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
    this.body = body;
  }

  /** True when the backend could not be reached at all. */
  get isOffline() {
    return this.status === 0;
  }
}

const buildUrl = (path, params) => {
  const url = new URL(
    `${API_BASE_URL.replace(/\/$/, '')}${path}`,
    window.location.origin,
  );
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, value);
      }
    });
  }
  return url.toString();
};

const extractErrorMessage = async (response) => {
  try {
    const data = await response.json();

    if (typeof data?.detail === 'string') return data.detail;

    // Structured detail from an endpoint that reports context alongside the
    // message (chat does this so the caller can recover the conversation).
    if (data?.detail?.message) return data.detail.message;

    // FastAPI validation errors. Include the offending field - a bare
    // "Field required" tells the user nothing about what to fix.
    if (Array.isArray(data?.detail)) {
      return data.detail
        .map((d) => {
          const field = Array.isArray(d.loc)
            ? d.loc.filter((part) => part !== 'body').join('.')
            : '';
          return field ? `${field}: ${d.msg}` : d.msg || JSON.stringify(d);
        })
        .join('; ');
    }

    return response.statusText || `Request failed (${response.status})`;
  } catch {
    return response.statusText || `Request failed (${response.status})`;
  }
};

/**
 * @param {string} path      Path below the API base, e.g. '/agents'
 * @param {object} [options] method, body, params, isFormData, signal
 */
export async function request(path, options = {}) {
  const {
    method = 'GET',
    body,
    params,
    isFormData = false,
    signal,
    // 'json' (default) or 'blob', for endpoints that return a file rather
    // than JSON. Identity travels in a header, so a file cannot simply be
    // linked to with an <a href> - it has to be fetched like any other call.
    responseType = 'json',
  } = options;

  const headers = {};
  const token = getActiveToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined && !isFormData) {
    headers['Content-Type'] = 'application/json';
  }

  const url = buildUrl(path, params);

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      signal,
      body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    // Network-level failure: server down, DNS, CORS rejection.
    throw new ApiError(
      'Cannot reach the workbench backend. Is the API running on ' +
        `${API_BASE_URL}?`,
      { status: 0, url, body: String(cause) },
    );
  }

  if (!response.ok) {
    throw new ApiError(await extractErrorMessage(response), {
      status: response.status,
      url,
    });
  }

  if (response.status === 204) return null;

  if (responseType === 'blob') {
    return {
      blob: await response.blob(),
      // The server names the file in Content-Disposition; prefer that over
      // anything the client guessed.
      filename: filenameFromDisposition(
        response.headers.get('Content-Disposition'),
      ),
    };
  }

  return response.json();
}

/**
 * Pull the filename out of a Content-Disposition header.
 *
 * Prefers the RFC 5987 `filename*` form, which is percent-encoded UTF-8 and
 * therefore survives names the plain quoted form has to mangle.
 */
export function filenameFromDisposition(disposition) {
  if (!disposition) return '';

  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      /* fall through to the plain form */
    }
  }

  const plain = /(?:^|;)\s*filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : '';
}

export const http = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
  patch: (path, body, options) => request(path, { ...options, method: 'PATCH', body }),
  del: (path, options) => request(path, { ...options, method: 'DELETE' }),
  upload: (path, formData, options) =>
    request(path, { ...options, method: 'POST', body: formData, isFormData: true }),
  /** GET a file. Resolves to { blob, filename }. */
  file: (path, options) =>
    request(path, { ...options, method: 'GET', responseType: 'blob' }),
};
