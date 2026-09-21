# Multi-platform official Python runtime
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and buffer outputs for real-time terminal display
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code, tests, and initial seed data
COPY src/ ./src/
COPY data/ ./data/
COPY tests/ ./tests/
COPY main.py .

# Define volume for data persistence across container runs
VOLUME ["/app/data"]

# Default command runs the interactive application, easily overridable for tests
CMD ["python", "main.py"]
