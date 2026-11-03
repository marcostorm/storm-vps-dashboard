FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client gosu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 1001 app \
 && mkdir -p /home/app/.ssh \
 && chown -R app:app /home/app /app \
 && chmod 700 /home/app/.ssh \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV HOME=/home/app

EXPOSE 8501

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["streamlit", "run", "src/storm_vps_dashboard/app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
