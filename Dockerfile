FROM python:3.10-slim

WORKDIR /app

# Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Make the start script executable
RUN chmod +x start.sh

# Run both the bot and the dashboard
CMD ["./start.sh"]
