# Start from a small, official Python base image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy just the requirements file first (this is a deliberate optimization — see explanation below)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of your actual code
COPY . .

# Tell Docker which port the app will run on
EXPOSE 8000

# The command that actually starts your app when the container runs
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]