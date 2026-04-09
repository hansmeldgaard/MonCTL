FROM python:3.12-slim

RUN pip install --no-cache-dir \
    pysnmp \
    pyasn1 \
    sortedcontainers \
    pyyaml \
    aiohttp

COPY simulator/ /app/simulator/

WORKDIR /app

ENTRYPOINT ["python", "-m", "simulator"]
