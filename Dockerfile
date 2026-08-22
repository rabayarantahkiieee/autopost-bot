# Dockerfile untuk PL News AutoPost Bot
# Dipakai di Sevalla (build type: Dockerfile) atau platform Docker lain.

FROM python:3.12-slim

# Supaya log langsung muncul di dashboard Sevalla (tanpa buffering)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependensi dulu (layer ini di-cache, build jadi cepat)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin kode bot
COPY bot.py .

# Folder data — di Sevalla, mount persistent disk ke /data
# dan set env DATA_DIR=/data supaya pengaturan awet saat redeploy
RUN mkdir -p /data
ENV DATA_DIR=/data

CMD ["python", "bot.py"]
