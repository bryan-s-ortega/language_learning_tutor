# Use a Python base image
FROM python:3.12-slim-bookworm

# Set environment variables for production performance
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOME=/app \
    PORT=8080 \
    PYTHONPATH=/app

# Set the working directory
WORKDIR $APP_HOME

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy only the dependency requirements first to leverage Docker cache
COPY pyproject.toml uv.lock ./

# Install project dependencies
RUN uv sync --frozen --no-dev

# Copy the application source code and static assets
COPY . .

# Expose the port Cloud Run expects
EXPOSE 8080

# Start the application using uvicorn via uv run
CMD ["uv", "run", "uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8080"]
