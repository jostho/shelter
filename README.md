# Shelter

![CI](https://github.com/jostho/shelter/workflows/CI/badge.svg)
![Image](https://github.com/jostho/shelter/workflows/Image/badge.svg)

This is a url shortener server written in python using [flask](https://github.com/pallets/flask).

## Environment

* fedora 38
* python 3.11
* make 4.4

## Setup

Create a virtualenv

    python3 -m venv shelter

Install python dependencies inside the virtualenv

    pip install -r requirements.txt

## Run

    ./shelter.py

## Image

A `Makefile` is provided to build a container image

Check prerequisites to build the image

    make check

To build the container image

    make image

To run the container image - use `podman`

    podman run -d -p 5000:5000 <imageid>
