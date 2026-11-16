# Polaris MIS - Backend Service

FastAPI production backend service for the Polaris MIS Dashboard.

## Project Structure
```
.
├── app/                  # FastAPI application modules
│   ├── main.py           # Application entrypoint & routes
│   ├── config.py         # Pydantic environment configuration
│   ├── db.py             # Database connection pooling (Psycopg 3)
│   ├── auth.py           # Authentication, JWT, and Google SSO
│   ├── analytics.py      # Analytics and KPI endpoints
│   ├── chart_data.py     # Aggregated chart endpoints
│   ├── ai.py             # AI Assistant query endpoints
│   └── ...
├── migrations/           # PostgreSQL schema migrations
├── tests/                # Automated pytest suite
├── manage.py             # CLI for migrations and user management
├── requirements.txt      # Production Python dependencies
├── requirements-dev.txt  # Development dependencies
├── pyproject.toml        # Tooling configuration
├── Dockerfile            # Container definition (Root-level)
├── .dockerignore
└── .env.example          # Environment variable template
```

## Running with Docker
```bash
docker build -t polaris-mis-backend .
docker run -p 8000:8000 --env-file .env polaris-mis-backend
```

## Running Locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
