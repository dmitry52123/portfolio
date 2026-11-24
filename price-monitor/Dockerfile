FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY monitor ./monitor
RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
ENV DB_PATH=/data/prices.db EXCEL_PATH=/data/prices.xlsx
CMD ["python", "-m", "monitor.cli", "--every", "60"]
