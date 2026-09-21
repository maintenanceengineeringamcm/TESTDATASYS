# One image for every HI process: the API + built UI, the configuration
# service, the 08:00 snapshot scheduler and the one-shot database restore.
# docker-compose.yml picks which one runs by overriding the command.

# ---------------------------------------------------------------- UI build
FROM node:20-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
# Bookworm (Debian 12) because Microsoft publishes the SQL Server ODBC driver
# for it; the plain python:3.13-slim tag has moved on to a newer Debian.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/mssql-tools18/bin:${PATH}"

# ODBC Driver 18 (what pyodbc talks through) plus sqlcmd for troubleshooting,
# since SSMS is not needed on the server. tzdata so the 08:00 job runs on
# local time rather than UTC.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg tzdata \
 && curl -fsSL -o /tmp/ms.deb https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
 && dpkg -i /tmp/ms.deb && rm /tmp/ms.deb \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 mssql-tools18 unixodbc \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY config-service/requirements.txt config-service/requirements.txt
RUN pip install -r backend/requirements.txt -r config-service/requirements.txt
# The DGA classifier in backend/ml_models was pickled with these exact
# versions; a different scikit-learn/XGBoost can refuse to load it.
# xgboost-cpu is the same library without the 300 MB of CUDA libraries.
RUN pip install numpy pandas "scikit-learn==1.8.0" "xgboost-cpu==3.2.0" joblib openpyxl

COPY backend/ backend/
COPY config-service/ config-service/
COPY docker/restore_databases.py docker/scheduler.py docker/
COPY --from=ui /ui/dist frontend/dist

ENV HI_HOST=0.0.0.0 \
    HI_PORT=5000 \
    HI_DEBUG=false \
    HI_FRONTEND_DIST=/app/frontend/dist \
    CFG_HOST=0.0.0.0 \
    CFG_DB_PATH=/data/config/config_store.db

WORKDIR /app/backend
EXPOSE 5000
CMD ["python", "serve.py"]
