# Use Microsoft's official Playwright image — Chromium + all deps pre-installed!
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Create runtime directories
RUN mkdir -p logs screenshots

# Railway injects PORT env variable — app.py reads os.getenv("PORT", 5000)
EXPOSE 5000

CMD ["python", "app.py"]
