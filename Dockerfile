# SPDX-License-Identifier: Apache-2.0
# Fingerprint Desk public demo. Single-process on purpose: SQLite + the
# in-process job queue want exactly one worker.
FROM python:3.12-slim

# libgl1/libglib2.0-0: opencv-python runtime deps on slim images. No system
# font is installed: the encoder uses the bundled Liberation Serif under
# assets/fonts/ (copied in below), so every deployment renders identical
# geometry regardless of host.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV FF_APPDATA=/data/appdata \
    HOST=0.0.0.0 \
    PORT=8765 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/repo
COPY requirements.txt ./requirements.txt
COPY app/requirements.txt ./app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r app/requirements.txt

COPY . .

VOLUME /data
EXPOSE 8765
CMD ["python", "app/serve.py"]
