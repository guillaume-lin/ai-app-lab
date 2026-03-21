# -------------------------
# Stage 1: Build Frontend
# -------------------------
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

# Install pnpm
RUN npm install -g pnpm

# Copy frontend source code
COPY frontend/code/package.json frontend/code/pnpm-lock.yaml ./
# Install dependencies
RUN pnpm install

# Copy the rest of frontend code
COPY frontend/code ./
# Build frontend
RUN pnpm run build

# -------------------------
# Stage 2: Build Backend & Final Image
# -------------------------
FROM python:3.9-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==1.8.3

# Copy backend poetry files
COPY backend/pyproject.toml backend/poetry.lock ./backend/

WORKDIR /app/backend
# Do not create a virtual environment, install directly into the system
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

# Copy backend source code
COPY backend/code ./code/

# Copy built frontend assets to backend static directory
COPY --from=frontend-builder /app/frontend/dist ./code/static

# Install aiofiles needed for StaticFiles (FastAPI uses it under the hood)
RUN pip install aiofiles

# Expose the port the app runs on
EXPOSE 8080

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PYTHONPATH=/app/backend

# The startup command
CMD ["python", "code/main.py"]
