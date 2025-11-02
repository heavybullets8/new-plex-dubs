# Use an official Python runtime as a parent image
FROM python:3.14-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app

# Define environment variable for the port and Plex credentials
ENV PORT 5000
ENV PLEX_URL=""
ENV PLEX_TOKEN=""
ENV PLEX_ANIME_SERIES=""
ENV PLEX_ANIME_MOVIES=""
ENV MAX_COLLECTION_SIZE 100
ENV MAX_DATE_DIFF 4

# Make port available to the world outside this container
EXPOSE $PORT

# Run app.py using Gunicorn when the container launches
CMD gunicorn --log-level info -w 1 --threads 4 -b 0.0.0.0:$PORT app:app
