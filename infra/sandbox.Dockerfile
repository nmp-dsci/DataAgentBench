# The execute_python sandbox: python:3.12-slim plus the analyst's libraries. Built once
# (`make sandbox`); run with --network none and one /work volume per run (agent/sandbox.py).
FROM python:3.12-slim
RUN pip install --no-cache-dir pandas==2.2.3 numpy==2.1.3 pyarrow==18.1.0 duckdb==1.1.3 scipy==1.14.1 python-dateutil==2.9.0.post0
WORKDIR /work
