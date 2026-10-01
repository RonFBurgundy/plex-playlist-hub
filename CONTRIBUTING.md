# Contributing to Plex Playlist Hub

Thank you for your interest in contributing to Plex Playlist Hub! We welcome community contributions, bug reports, feature suggestions, and documentation improvements.

---

## Code of Conduct

Please treat everyone with respect, kindness, and empathy. Be constructive, open to feedback, and collaborative.

---

## Development Workflow

1. **Fork the Repository**:
   - Fork `RonFBurgundy/plex-playlist-hub` to your personal GitHub account.
   - Clone your fork locally:
     ```bash
     git clone https://github.com/<your-username>/plex-playlist-hub.git
     cd plex-playlist-hub
     ```

2. **Create a Feature Branch**:
   - Create a descriptive branch branching off `main`:
     ```bash
     git checkout -b feature/your-feature-name
     # or
     git checkout -b fix/issue-description
     ```

3. **Set Up the Development Environment**:
   - Python 3.12 is recommended.
   - Install dependencies:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     pip install -r requirements-dev.txt
     ```

4. **Run the Test Suite**:
   - Run tests directly:
     ```bash
     pytest -v
     ```
   - Or run tests inside an isolated Docker container (matching CI):
     ```bash
     docker run --rm -v "$PWD":/app -w /app -e PYTHONPATH=/app python:3.12-slim bash -c "pip install -q -r requirements-dev.txt && pytest -v"
     ```

5. **Verify Docker Build**:
   - Ensure the container builds cleanly:
     ```bash
     docker build -t plex-playlist-hub:dev .
     ```

---

## Coding & Security Standards

To keep Plex Playlist Hub secure, maintainable, and robust, all pull requests must follow these rules:

- **Security First**:
  - Never execute dynamic SQL strings. Always use parameterized queries (`?`) in SQLite.
  - Validate and sanitize external input (URLs, track titles, image URLs).
  - Do not use shell execution (`subprocess`, `os.system`).
  - Never commit real API keys, tokens, or credentials.
- **Type Annotations**:
  - Use Python type hints on all new functions and endpoints.
- **Tests Required**:
  - Every new feature or bug fix must include corresponding tests in `tests/`.
  - 100% of existing and new tests must pass before merging.
- **Commit Messages**:
  - Follow standard conventional commits format (e.g. `feat: add deezer user mixes`, `fix: handle edge case in track matching`, `docs: update setup guide`).

---

## Submitting a Pull Request

1. Push your branch to your GitHub fork:
   ```bash
   git push -u origin feature/your-feature-name
   ```
2. Open a Pull Request against the `main` branch of `RonFBurgundy/plex-playlist-hub`.
3. Complete the PR template checklist.
4. GitHub Actions CI will automatically run the test suite and CodeQL security analysis against your PR.
5. Maintainers will review your PR and provide constructive feedback!
