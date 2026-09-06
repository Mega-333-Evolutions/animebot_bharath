FROM python:3.8-slim-buster
WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

# Expose the port Hugging Face looks for
EXPOSE 7860

# Start a dummy web server on port 7860 in the background, then start your bot
CMD python3 -m http.server 7860 & python3 main.py
