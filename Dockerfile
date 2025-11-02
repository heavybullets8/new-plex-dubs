FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV PORT=5000 \
    MAX_COLLECTION_SIZE=100 \
    MAX_DATE_DIFF=4

EXPOSE $PORT

CMD ["sh", "-c", "gunicorn --log-level info -w 1 --threads 4 -b 0.0.0.0:$PORT app:app"]
