/**
 * Central API Client for TrackSeerr React SPA.
 * Handles authentication tokens, JSON serialization, and error dispatching.
 */

const TOKEN_KEY = 'trackseerr_auth_token';

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
}

/** Error carrying the HTTP status so callers can map specific failures. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function apiRequest<T>(
  endpoint: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let bodyContent: BodyInit | null | undefined = undefined;
  if (options.body !== undefined && options.body !== null) {
    if (typeof options.body === 'string') {
      bodyContent = options.body;
      if (options.body.startsWith('{') || options.body.startsWith('[')) {
        headers['Content-Type'] = 'application/json';
      }
    } else if (options.body instanceof FormData) {
      bodyContent = options.body;
    } else {
      headers['Content-Type'] = 'application/json';
      bodyContent = JSON.stringify(options.body);
    }
  }

  // Merge extra headers from options
  if (options.headers) {
    if (options.headers instanceof Headers) {
      options.headers.forEach((val, key) => {
        headers[key] = val;
      });
    } else if (Array.isArray(options.headers)) {
      for (const [key, val] of options.headers) {
        headers[key] = val;
      }
    } else {
      Object.assign(headers, options.headers);
    }
  }

  const response = await fetch(endpoint, {
    ...options,
    headers,
    body: bodyContent,
    credentials: 'same-origin',
  });

  if (response.status === 401) {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('trackseerr:unauthorized'));
    }
    throw new Error('Unauthorized');
  }

  if (response.status === 204) {
    return null as T;
  }

  const data: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const errorData = data as { detail?: string | Array<{ msg: string }> } | null;
    let detailMsg = `HTTP Error ${response.status}: ${response.statusText}`;
    if (errorData?.detail) {
      if (typeof errorData.detail === 'string') {
        detailMsg = errorData.detail;
      } else if (Array.isArray(errorData.detail)) {
        detailMsg = errorData.detail.map((e) => e.msg).join('; ');
      }
    }
    throw new ApiError(detailMsg, response.status);
  }

  return data as T;
}
