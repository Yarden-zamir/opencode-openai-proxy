FROM python:3.14-slim

WORKDIR /app
COPY proxy.py /app/proxy.py

# Stdlib-only proxy; no dependencies to install.
CMD ["python", "-u", "/app/proxy.py"]
