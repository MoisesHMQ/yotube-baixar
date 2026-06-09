FROM python:3.12-slim

# Install ffmpeg for yt-dlp video+audio merging
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY Untitled-1.py ./
RUN mkdir -p /app/videos

EXPOSE 8000

CMD ["python", "Untitled-1.py"]
