FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire backend
COPY . .

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
