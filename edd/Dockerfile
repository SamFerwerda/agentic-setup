# Eval runner; docker-compose.yaml mounts edd/ at /edd, so case edits need no rebuild.
FROM python:3.13-slim
WORKDIR /edd
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
CMD ["pytest", "-p", "no:cacheprovider"]
