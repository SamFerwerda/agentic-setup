# Shared image for every agent; pick one with the AGENT build arg (e.g. supervisor).
FROM python:3.13-slim
WORKDIR /app
COPY common/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
ARG AGENT
COPY agents/${AGENT} ./agent
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
