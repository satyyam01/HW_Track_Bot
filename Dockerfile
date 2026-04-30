# Use the official Playwright image which includes all dependencies for Chromium
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set the working directory
WORKDIR /app

# Copy requirement files and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install chromium browser
RUN playwright install chromium

# Copy the rest of the application
COPY . .

# Run the script
CMD ["python", "watcher.py"]
