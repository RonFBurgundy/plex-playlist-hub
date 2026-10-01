# Security Policy

## Reporting Security Issues

If you discover a security vulnerability within Plex Playlist Hub, please **do not** open a public issue. Instead, report it privately via GitHub Security Advisories or by contacting the maintainers directly through GitHub.

All security reports are acknowledged within 48 hours, and patches are prioritized.

---

## Security Model & Threat Defenses

Plex Playlist Hub is designed to be safe for reverse-proxy and internet exposure (similar to Overseerr / Jellyseerr).

### 1. Server-Side Request Forgery (SSRF) Defense
- The server **never** performs arbitrary outbound HTTP requests to user-provided URLs or hostnames.
- Playlist inputs are validated using strict regex patterns that extract only valid alphanumeric Spotify IDs or numerical Deezer IDs.
- Localhost, loopback, private RFC-1918 addresses, and cloud metadata IP addresses (`169.254.169.254`) are structurally rejected before any request can occur.

### 2. Zero Subprocess Execution
- No API route invokes `subprocess`, `os.system`, or shell interpreters. All library interactions are strictly in-process Python SDK operations.

### 3. Path Traversal Containment
- All file exports and data writes are strictly verified against `DATA_DIR` containment using path resolution (`.resolve().is_relative_to(DATA_DIR)`). Directory escape attempts (`../`) raise an immediate `ValueError`.

### 4. Injection Defense
- 100% of SQLite database interactions use parameterized queries (`?` bindings). Zero dynamic SQL string concatenation is permitted.
- User-provided text strings are stripped of HTML tags and control characters to prevent cross-site scripting (XSS).

### 5. Least-Privilege Execution
- The official Docker image executes as an unprivileged non-root user (`appuser:uid 1000`).
- No Docker socket (`/var/run/docker.sock`) is required or used.
