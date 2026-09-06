FROM python:3.8-slim-buster
WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

CMD while true; do python3 main.py; echo "main.py exited — restarting in 3s"; sleep 3; done
