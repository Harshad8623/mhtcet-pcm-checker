FROM python:3.11-slim

# Install ALL Playwright/Chromium system dependencies
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    # Chromium core
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 \
    # X11
    libx11-6 libx11-xcb1 libxcb1 libxext6 libxrender1 \
    # Fonts
    fonts-liberation fonts-noto-color-emoji \
    # Extra
    libvulkan1 libGL1-mesa-glx xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium

# Copy all project files
COPY . .

# Create runtime directories
RUN mkdir -p logs screenshots

# Railway injects PORT automatically — app.py reads it
EXPOSE 5000

CMD ["python", "app.py"]
