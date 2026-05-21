# ASC API

Flask-based backend API for analytics, attendance, and user authentication used by ASC applications.

## What the project does

- Provides REST endpoints for analytics, attendance tracking, and authentication (Firebase + JWT).
- Uses SQLAlchemy + Flask-Migrate for persistence and migrations, with optional PostgreSQL support.
- Integrates with Google Cloud (Firestore / Storage) and Firebase Admin for auth and emulators.

## Why this project is useful

- Lightweight, modular Flask API split into clear blueprints: auth, analytics, attendance, core.
- Ready for production deployment (Gunicorn) and local development (dev server + Firebase emulators).
- Batteries-included dependencies for data export (pandas, openpyxl, xlsxwriter) and cloud integration.

## Quick links

- Code: [app](app)
- Configuration: [app/config.py](app/config.py)
- Run entrypoint: [run.py](run.py)
- Dependencies: [requirements.txt](requirements.txt)
- Firebase emulators config: [firebase.json](firebase.json)

## Prerequisites

- Python 3.10+ (match your environment)
- PostgreSQL (optional) or use the bundled SQLite fallback
- Firebase CLI (if you plan to run Firebase emulators)

## Get started (local)

1. Clone the repo:

   git clone <repo-url>
   cd asc-api

2. Create and activate a virtual environment:

   python -m venv .venv
   source .venv/bin/activate

3. Install Python dependencies:

   pip install -r requirements.txt

4. Configure environment variables (examples):

   export SECRET_KEY="a-strong-secret"
   export DATABASE_URL="postgresql://user:pass@host:5432/dbname"

   - If `DATABASE_URL` is not set, the app will use a SQLite file at `app/app.db`.
   - See [app/config.py](app/config.py) for details.

5. Run database migrations (Flask-Migrate):

   export FLASK_APP=run.py
   flask db upgrade

   If this is the first time, initialize migrations with `flask db init`.

6. Start the server (development):

   python run.py

   Or run with Gunicorn for production-style testing:

   gunicorn -w 4 run:app -b 0.0.0.0:5001

7. (Optional) Start Firebase emulators for local auth/firestore testing:

   firebase emulators:start

## Usage examples

- Health check:

  GET /

  Response: `{"status": "ok"}`

- Authentication, analytics, attendance and other routes are mounted as blueprints under `app`.
  Explore the handlers in the `app/auth`, `app/analytics`, and `app/attendance` directories.

Example: curl a protected route (replace token and path):

  curl -H "Authorization: Bearer <JWT>" http://localhost:5001/api/some-endpoint

## Configuration

- Environment-driven via `app/config.py`.
- Important variables:
  - `SECRET_KEY` — session/JWT secret
  - `DATABASE_URL` — SQLAlchemy database URI (Postgres preferred)

## Project layout (high level)

- `run.py` — application entrypoint
- `app/` — Flask app package
  - `auth/` — authentication-related routes and Firebase integration
  - `analytics/` — analytics routes and report generators
  - `attendance/` — attendance API
  - `models/` — SQLAlchemy models
  - `extensions.py` — `db`, `migrate` instances

## Where to get help

- Open an issue in this repository for bugs or feature requests.
- For Firebase emulator usage, see `firebase.json` and Firebase docs.

## Who maintains and contributes

- Maintainers: project team (see `CONTRIBUTING.md` for contributor guidelines).
- Contributions: please follow the process in `CONTRIBUTING.md` and submit pull requests.

## Links

- Contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- License: [LICENSE](LICENSE)