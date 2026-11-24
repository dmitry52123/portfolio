FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
RUN useradd --create-home botuser && mkdir -p /data && chown botuser /data
USER botuser
ENV DB_PATH=/data/bookings.db
CMD ["python", "-m", "bot.main"]
