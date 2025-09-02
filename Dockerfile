FROM python:3.11-slim

WORKDIR /home/websocket_server

# Create logs directory
RUN mkdir -p logs

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server file and .env
COPY server.py .
COPY .env .

# Create non-root user for security
RUN useradd -m -s /bin/bash wsuser && \
    chown -R wsuser:wsuser /home/websocket_server

USER wsuser

# Expose WebSocket port
EXPOSE 8443

# Start the server
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8443"]
