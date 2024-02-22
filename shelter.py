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
from flask import Flask, Response, jsonify, make_response, redirect, request, send_file
from prometheus_client import Counter, disable_created_metrics, make_wsgi_app
from werkzeug.middleware.dispatcher import DispatcherMiddleware

APP_NAME = "shelter"
APP_VERSION = "0.1.0"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
DEFAULT_KEY_LENGTH = 4

CONTENT_TYPE_TEXT = "text/plain"
CONTENT_TYPE_JSON = "application/json"

# db file location
ENV_DB_FILE = "SHELTER_DB"
DEFAULT_DB_FILE = "/tmp/shelter.pickle"

# release file location
ENV_RELEASE_FILE = "SHELTER_RELEASE"
DEFAULT_RELEASE_FILE = "/usr/local/etc/shelter-release"

# env variable name for cidr allow list - default []
# 1. list of values (read as json) - e.g. '["10.42.10.0/24", "1.1.1.1"]'
# 2. single value - e.g. '10.42.10.0/24'
ENV_CIDR_ALLOW = "SHELTER_CIDR_ALLOW"

# env variable name to control throttling
# to turn on throttling - pass in a value > 0
ENV_THROTTLE_RPM_LIMIT = "SHELTER_THROTTLE_RPM_LIMIT"

# env variable name to control sleep
# to turn on sleep - pass in a value > 0
ENV_SLEEP_MAX_SECONDS = "SHELTER_SLEEP_MAX_SECONDS"

# number of nano seconds in a minute
ONE_MINUTE_IN_NANOS = 60 * 1000 * 1000 * 1000

# track ips for throttled urls
rate_limit_ip_tracker = {}

# flask app
app = Flask(__name__)

# add prometheus wsgi middleware to flask
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/metrics": make_wsgi_app()})

# disable '_created' timestamp metric
disable_created_metrics()

# failure counters
counter_s_get_failures = Counter("shelter_s_get_failures", "shelter short url failures")
counter_api_get_failures = Counter(
    "shelter_api_get_failures", "shelter api get failures"
)
counter_api_post_failures = Counter(
    "shelter_api_post_failures", "shelter api post failures"
)


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


def _db_file():
    return os.getenv(ENV_DB_FILE, DEFAULT_DB_FILE)


def _read():
    db = {"urls": {}}
    db_file = _db_file()
    if Path(db_file).is_file():
        with open(db_file, "rb") as infile:
            db = pickle.load(infile)
    return db


def _save(db):
    db_file = _db_file()
    with open(db_file, "wb") as outfile:
        pickle.dump(db, outfile)


def _add_url(input_json):
    db = _read()
    item = None
    if "url" in input_json and input_json["url"]:
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


def _whoami():
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


def _release_file():
    env_file = os.getenv(ENV_RELEASE_FILE, DEFAULT_RELEASE_FILE)
    if Path(env_file).is_file():
        return env_file


def _ip_local(remote_ip):
    return remote_ip == "127.0.0.1"


def _cidr_allow_list():
    allow_list = []
    env_cidr_allow = os.getenv(ENV_CIDR_ALLOW)
    if env_cidr_allow:
        try:
            if env_cidr_allow.startswith("["):
                # list of values, read as json
                allow_list = json.loads(env_cidr_allow)
            else:
                # single value, used as-is
                allow_list = [env_cidr_allow]
            # verify what we got
            for cidr in allow_list:
                ipaddress.ip_network(cidr)
        except ValueError:
            allow_list = []
    return allow_list


def _sleep_max_seconds():
    return int(os.getenv(ENV_SLEEP_MAX_SECONDS, 0))


def _ip_allowed(remote_ip):
    if _ip_local(remote_ip):
        return True
    allow_list = _cidr_allow_list()
    for cidr in allow_list:
        if ipaddress.ip_address(remote_ip) in ipaddress.ip_network(cidr):
            return True
    # if you reach here, bad luck
    return False


def _throttle_rpm_limit():
    return int(os.getenv(ENV_THROTTLE_RPM_LIMIT, 0))


def _throttle_enabled():
    return _throttle_rpm_limit() > 0


def _refill_ip():
    return dict(epoch=time.time_ns(), available=_throttle_rpm_limit() - 1)


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


@app.route("/release")
def release():
    release_file = _release_file()
    if release_file:
        return send_file(release_file, mimetype=CONTENT_TYPE_TEXT)
    else:
        return Response(
            response="Not Found", status=404, content_type=CONTENT_TYPE_TEXT
        )


@app.route("/whoami")
def whoami():
    result = _whoami()
    return jsonify(result)


@app.route("/internal/headers")
def headers():
    response = f"Headers\n{request.headers}"
    return Response(response=response, status=200, content_type=CONTENT_TYPE_TEXT)


@app.route("/internal/status/<int:status_code>")
def status(status_code):
    response_code = status_code if status_code > 200 and status_code < 600 else 200
    response = f"Status: {response_code}"
    return Response(
        response=response, status=response_code, content_type=CONTENT_TYPE_TEXT
    )


@app.route("/internal/sleep/<int:seconds>")
def sleep(seconds):
    if seconds < _sleep_max_seconds():
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


@app.route("/api/<key>")
def api_with_key(key):
    if not _ip_throttled(request.remote_addr):
        result = _get_url_item_for_api(key)
        if "message" in result:
            counter_api_get_failures.inc()
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
            if request.get_json(silent=True):
                result = _add_url(request.get_json())
                if "message" in result:
                    counter_api_post_failures.inc()
                    return make_response(jsonify(result), 400)
            else:
                result = dict(message="request is not json")
                counter_api_post_failures.inc()
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
        counter_s_get_failures.inc()
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
