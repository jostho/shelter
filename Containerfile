# python 3.10-slim
FROM docker.io/library/python:3.10-slim
COPY requirements.txt shelter.py /usr/local/src/shelter/
COPY meta.version /usr/local/etc/shelter-release
RUN python --version >> /usr/local/etc/shelter-release
WORKDIR /usr/local/src/shelter
RUN pip install -r requirements.txt
CMD ["/usr/local/bin/gunicorn", "shelter:app"]
EXPOSE 5000
ENV GUNICORN_CMD_ARGS="--bind 0.0.0.0:5000 \
 --access-logfile=- \
 --access-logformat='%(h)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\" \"%({Host}i)s\" %(p)s %(L)s'"
