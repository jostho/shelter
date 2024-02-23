# Shelter

![CI](https://github.com/jostho/shelter/actions/workflows/ci.yml/badge.svg)
![Image](https://github.com/jostho/shelter/actions/workflows/image.yml/badge.svg)

This is a url shortener server written in python using [flask](https://github.com/pallets/flask).

## Environment

* fedora 39
* python 3.12
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
