// The optional bearer token (set only when the backend has MAKI_AUTH_TOKEN). Stored in
// localStorage, which is origin-scoped: a malicious site on another origin cannot read it.
const KEY = "maki-auth-token";

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string): void {
  localStorage.setItem(KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(KEY);
}
