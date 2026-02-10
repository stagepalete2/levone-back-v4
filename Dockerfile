# Use Ubuntu-based Python image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt gunicorn

# Copy project files
COPY . .

RUN useradd -m -u 1000 django_user

# Create directories for static and media
RUN mkdir -p /app/staticfiles /app/media && \
    chown -R 1000:1000 /app

# Security: Create non-root user

USER django_user

EXPOSE 7000

CMD ["gunicorn", \
     "--bind", "0.0.0.0:7000", \
     "--workers", "2", \
     "--threads", "2", \
     "main.wsgi:application"]
