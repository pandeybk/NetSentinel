FROM python:3.10.11-bullseye

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libhdf5-dev \
    libopenblas-dev \
    libomp-dev \
    cmake \
    libcurl4-openssl-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to the latest version
RUN pip install --upgrade pip

# Download wait-for-it.sh script using curl
RUN curl -o /wait-for-it.sh https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh && \
    chmod +x /wait-for-it.sh

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt ./
RUN pip install packaging==20.9
RUN pip install --no-cache-dir --no-deps -r requirements.txt
RUN pip install tensorflow
# RUN pip install --no-cache-dir -r requirements.txt


# Copy all the application files
COPY . .

# Allow overriding the command using an environment variable
ENV PYTHONPATH=/app

# Set entrypoint
ENTRYPOINT ["./entrypoint.sh"]

# Default command to run the main application
CMD ["python", "app/run.py"]
