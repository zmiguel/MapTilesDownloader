FROM python:3.13

WORKDIR /app
COPY src/requirements.txt ./

RUN pip install -r requirements.txt

# Add environment variable with a default value
ENV MAPBOX_ACCESS_TOKEN=""

# Consider adding a volume for persistent storage
VOLUME ["/app/output"]

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:8080/ || exit 1

# Bundle app source
COPY src /app

EXPOSE 8080
CMD [ "python", "server.py" ]