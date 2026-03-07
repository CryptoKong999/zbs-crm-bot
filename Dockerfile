FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY . .

# Set timezone
ENV TZ=Asia/Tashkent

CMD ["python", "bot.py"]
