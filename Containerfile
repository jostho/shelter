# python 3.9-slim
FROM docker.io/library/python:3.9-slim
COPY requirements.txt /usr/local/src/shelter/
COPY shelter.py /usr/local/bin
RUN pip install -r /usr/local/src/shelter/requirements.txt
CMD ["/usr/local/bin/shelter.py"]
EXPOSE 5000
