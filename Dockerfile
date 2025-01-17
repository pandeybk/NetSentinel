# Stage 1 - Base setup with system dependencies
FROM python:3.10.11-bullseye as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install essential dependencies and git-lfs for model downloading
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libhdf5-dev \
    libopenblas-dev \
    libomp-dev \
    cmake \
    libcurl4-openssl-dev \
    libssl-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

# Download wait-for-it.sh script using curl
RUN curl -o /wait-for-it.sh https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh && \
    chmod +x /wait-for-it.sh

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --no-deps -r requirements.txt
RUN pip install packaging==20.9
RUN pip install tensorflow 
RUN pip install torch torchvision torchaudio
RUN pip install kaggle

COPY . .

# Train NLU models
RUN rm -rf /app/models/rasa/*
RUN rasa train --config /app/rasa/config.yml --domain /app/rasa/domain.yml --data /app/rasa --out /app/models/rasa/
RUN mv /app/models/rasa/*.gz /app/models/rasa/nlu-model.gz

# Set environment path and entrypoint
ENV PYTHONPATH=/app
ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "app/run.py"]
