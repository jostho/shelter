#!/usr/bin/env python3

# url shortener server

import ipaddress
import json
import os
import pickle
import platform
import random
import string
import time
from pathlib import Path

import click
from flask import Flask, Response, jsonify, make_response, redirect, request

APP_NAME = "shelter"
APP_VERSION = "0.1.0"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000

DB_FILE = "/tmp/shelter.pickle"
DEFAULT_KEY_LENGTH = 4

CONTENT_TYPE_TEXT = "text/plain"
CONTENT_TYPE_JSON = "application/json"

# env variable name for cidr allow list
ENV_CIDR_ALLOW = "SHELTER_CIDR_ALLOW"

# env variable name to control throttling
ENV_THROTTLE = "SHELTER_THROTTLE"

# requests per minute limit for throttled urls
LIMIT_RPM = 15

# number of nano seconds in a minute
ONE_MINUTE_IN_NANOS = 60 * 1000 * 1000 * 1000

# track ips for throttled urls
rate_limit_ip_tracker = {}

app = Flask(__name__)


def _get_runtime_version():
    return f"{platform.python_implementation()}/{platform.python_version()}"


def _get_version_message():
    return f"{APP_NAME} {APP_VERSION} ({_get_runtime_version()})"


def _prepare_url_dict(input_json):
    epoch = input_json["epoch"] if "epoch" in input_json else time.time_ns()
    return dict(url=input_json["url"], epoch=epoch, hits=0)


def _get_random_key(key_length=DEFAULT_KEY_LENGTH):
    return "".join(random.choices(string.ascii_uppercase, k=key_length))


def _init():
    db = {"urls": {}}
    _save(db)


def _read():
    db = {"urls": {}}
    if Path(DB_FILE).is_file():
        with open(DB_FILE, "rb") as infile:
            db = pickle.load(infile)
    return db


def _save(db):
    with open(DB_FILE, "wb") as outfile:
        pickle.dump(db, outfile)


def _add_url(input_json):
    db = _read()
    item = None
    if "url" in input_json:
        s_key = _get_random_key()
        if s_key not in db["urls"]:
            s_val = _prepare_url_dict(input_json)
            item = {s_key: s_val}
            db["urls"].update(item)
            _save(db)
        else:
            item = dict(message="key is taken")
    else:
        item = dict(message="url not found")
    return item


def _get_urls():
    db = _read()
    return db["urls"]


def _get_url_item_for_api(key):
    db = _read()
    item = None
    if key in db["urls"]:
        item = db["urls"][key]
    else:
        item = dict(message="url not found")
    return item


def _get_url_for_redirect(key):
    db = _read()
    url = None
    if key in db["urls"]:
        url = db["urls"][key]["url"]
        db["urls"][key]["hits"] += 1
        _save(db)
    return url


def _status():
    db = _read()
    result = dict(
        hostname=platform.node(),
        pid=os.getpid(),
        total_url=len(db["urls"]),
    )
    if _throttle_enabled():
        # provide only IPs active in the last 1 minute
        now = time.time_ns()
        ip_tracker = {
            key: val
            for key, val in rate_limit_ip_tracker.items()
            if now < val["epoch"] + ONE_MINUTE_IN_NANOS
        }
        result["ip_tracker"] = ip_tracker
    return result


def _ip_local(remote_ip):
    return remote_ip == "127.0.0.1"


def _cidr_allow_list():
    allow_list = []
    if ENV_CIDR_ALLOW in os.environ:
        try:
            if os.environ[ENV_CIDR_ALLOW].startswith("["):
                # list of values - e.g. '["10.42.10.0/24", "1.1.1.1"]'
                allow_list = json.loads(os.environ[ENV_CIDR_ALLOW])
            else:
                # single value - e.g. '10.42.10.0/24'
                allow_list = [os.environ[ENV_CIDR_ALLOW]]
            # verify what we got
            for cidr in allow_list:
                ipaddress.ip_network(cidr)
        except ValueError:
            allow_list = []
    return allow_list


def _ip_allowed(remote_ip):
    if _ip_local(remote_ip):
        return True
    allow_list = _cidr_allow_list()
    for cidr in allow_list:
        if ipaddress.ip_address(remote_ip) in ipaddress.ip_network(cidr):
            return True
    # if you reach here, bad luck
    return False


def _refill_ip():
    return dict(epoch=time.time_ns(), available=LIMIT_RPM - 1)


def _throttle_enabled():
    return os.getenv(ENV_THROTTLE) in ("true", "1")


def _ip_throttled(remote_ip):
    if not _throttle_enabled() or _ip_local(remote_ip):
        return False
    if remote_ip in rate_limit_ip_tracker:
        ip_details = rate_limit_ip_tracker[remote_ip]
        now = time.time_ns()
        # refill if more than a minute has passed
        if now > ip_details["epoch"] + ONE_MINUTE_IN_NANOS:
            rate_limit_ip_tracker[remote_ip] = _refill_ip()
            return False
        # decrement if you are inside the one minute
        if ip_details["available"] > 0:
            ip_details["available"] -= 1
            rate_limit_ip_tracker[remote_ip] = ip_details
            return False
    else:
        rate_limit_ip_tracker[remote_ip] = _refill_ip()
        return False
    # if you reach here, bad luck
    return True


@app.route("/")
def index():
    return f"Welcome to {APP_NAME}"


@app.route("/healthcheck")
def healthcheck():
    return Response(response="Ok", status=200, content_type=CONTENT_TYPE_TEXT)


@app.route("/version")
def version():
    response = f"{APP_VERSION} ({_get_runtime_version()})"
    return Response(response=response, status=200, content_type=CONTENT_TYPE_TEXT)


@app.route("/sleep/<int:seconds>")
def sleep(seconds):
    max_seconds = 10
    if _ip_allowed(request.remote_addr) and seconds < max_seconds:
        time.sleep(seconds)
        return Response(response="Woke", status=200, content_type=CONTENT_TYPE_TEXT)
    else:
        return Response(
            response="Forbidden", status=403, content_type=CONTENT_TYPE_TEXT
        )


@app.route("/init", methods=["POST"])
def init():
    if _ip_allowed(request.remote_addr):
        _init()
        return Response(response="Ok", status=200, content_type=CONTENT_TYPE_TEXT)
    else:
        return Response(
            response="Forbidden", status=403, content_type=CONTENT_TYPE_TEXT
        )


@app.route("/status")
def status():
    result = _status()
    return jsonify(result)


@app.route("/api/<key>")
def api_with_key(key):
    if not _ip_throttled(request.remote_addr):
        result = _get_url_item_for_api(key)
        if "message" in result:
            return make_response(jsonify(result), 400)
        else:
            return jsonify(result)
    else:
        result = dict(message="Too Many Requests")
        return make_response(jsonify(result), 429)


@app.route("/api", methods=["GET", "POST"])
def api():
    if not _ip_throttled(request.remote_addr):
        if request.method == "POST":
            if request.get_json():
                result = _add_url(request.get_json())
                if "message" in result:
                    return make_response(jsonify(result), 400)
            else:
                result = dict(message="request is not json")
                return make_response(jsonify(result), 400)
        else:
            result = _get_urls()
        return jsonify(result)
    else:
        result = dict(message="Too Many Requests")
        return make_response(jsonify(result), 429)


@app.route("/s/<key>")
def short(key):
    url = _get_url_for_redirect(key)
    if url:
        return redirect(url)
    else:
        return Response(
            response="Not Found", status=404, content_type=CONTENT_TYPE_TEXT
        )


@click.command()
@click.option(
    "--host",
    "-h",
    default=DEFAULT_HOST,
    show_default=True,
    help="host",
)
@click.option(
    "--port",
    "-p",
    default=DEFAULT_PORT,
    show_default=True,
    help="port",
)
@click.version_option(version=APP_VERSION, message=_get_version_message())
def cli(host, port):
    """shelter server"""
    app.run(host=host, port=port)


if __name__ == "__main__":
    cli(auto_envvar_prefix="SHELTER")
