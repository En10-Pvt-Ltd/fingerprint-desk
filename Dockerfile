# SPDX-License-Identifier: Apache-2.0
# Fingerprint Desk public demo. Single-process on purpose: SQLite + the
# in-process job queue want exactly one worker.
FROM python:3.12-slim

# fonts-dejavu-core: the encoder requires a serif TTF (DejaVuSerif).
# libgl1/libglib2.0-0: opencv-python runtime deps on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV FF_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf \
    FF_APPDATA=/data/appdata \
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
