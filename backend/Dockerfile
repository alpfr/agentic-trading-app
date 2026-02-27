FROM python:3.11-slim

WORKDIR /app

# Ensure we have the base build tools and libpq
RUN apt-get update && apt-get install -y build-essential curl

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# We explicitly install uvicorn
RUN pip install fastapi uvicorn requests

COPY . .

# Run uvicorn on port 8000 (standard for kubernetes)
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
