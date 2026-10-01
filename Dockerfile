FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

EXPOSE 7860

CMD ["./entrypoint.sh"]
