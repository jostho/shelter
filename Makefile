
# required binaries
PYTHON := python3
BUILDAH := buildah
GIT := git
PODMAN := podman

ARCH = $(shell arch)

GIT_BRANCH := $(shell $(GIT) rev-parse --abbrev-ref HEAD)
GIT_COMMIT := $(shell $(GIT) rev-parse --short HEAD)
GIT_VERSION := $(GIT_BRANCH)/$(GIT_COMMIT)

APP_OWNER := jostho
APP_NAME := shelter
APP_VERSION := $(shell $(PYTHON) -c 'import shelter; print(shelter.APP_VERSION)')
APP_REPOSITORY := https://github.com/$(APP_OWNER)/$(APP_NAME)

IMAGE_BINARY_PATH := /usr/local/bin/$(APP_NAME).py

# github action sets "CI=true"
ifeq ($(CI), true)
IMAGE_PREFIX := ghcr.io/$(APP_OWNER)
IMAGE_VERSION := $(GIT_COMMIT)
else
IMAGE_PREFIX := $(APP_OWNER)
IMAGE_VERSION := v$(APP_VERSION)
endif

check: check-required check-optional

check-required:
	$(PYTHON) --version

check-optional:
	$(BUILDAH) --version
	$(GIT) --version
	$(PODMAN) --version

build-image: BASE_IMAGE = python
build-image:
	$(BUILDAH) bud \
		--tag $(IMAGE_NAME) \
		--label app-name=$(APP_NAME) \
		--label app-version=$(APP_VERSION) \
		--label app-git-version=$(GIT_VERSION) \
		--label app-arch=$(ARCH) \
		--label app-base-image=$(BASE_IMAGE) \
		--label org.opencontainers.image.source=$(APP_REPOSITORY) \
		-f Containerfile .

verify-image:
	$(BUILDAH) images
	$(PODMAN) run $(IMAGE_NAME) $(IMAGE_BINARY_PATH) --version

push-image:
ifeq ($(CI), true)
	$(BUILDAH) push $(IMAGE_NAME)
endif

image: IMAGE_NAME = $(IMAGE_PREFIX)/$(APP_NAME):$(IMAGE_VERSION)
image: build-image verify-image push-image

.PHONY: check check-required check-optional
.PHONY: build-image image
.PHONY: verify-image push-image
