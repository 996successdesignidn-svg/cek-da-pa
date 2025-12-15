FROM python:3.11-slim

# Install Chromium dan driver untuk Selenium
RUN apt-get update && \
    apt-get install -y chromium chromium-driver && \
    rm -rf /var/lib/apt/lists/*

# Set working directory di dalam container
WORKDIR /app

# Copy semua file dari repo ke dalam container
COPY . .

# Install library Python
RUN pip install --no-cache-dir -r requirements.txt

# Command yang dijalankan saat container start
CMD ["python", "check_domains.py"]
