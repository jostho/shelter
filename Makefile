
# required binaries
PYTHON := python3
BUILDAH := buildah
GIT := git
PODMAN := podman
CURL := curl

ARCH = $(shell arch)

GIT_BRANCH := $(shell $(GIT) rev-parse --abbrev-ref HEAD)
GIT_COMMIT := $(shell $(GIT) rev-parse --short HEAD)
GIT_VERSION := $(GIT_BRANCH)/$(GIT_COMMIT)

APP_OWNER := jostho
APP_NAME := shelter
APP_VERSION := 0.1.0
APP_REPOSITORY := https://github.com/$(APP_OWNER)/$(APP_NAME)

LOCAL_META_VERSION_PATH := $(CURDIR)/meta.version

BASE_IMAGE=python-slim
PORT := 5000

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
	$(CURL) --version | head -1

clean:
	rm -f $(LOCAL_META_VERSION_PATH)

prep-version-file:
	echo "$(APP_NAME) $(APP_VERSION) ($(GIT_COMMIT))" > $(LOCAL_META_VERSION_PATH)

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

build-multiarch-image:
	$(BUILDAH) bud \
		--manifest $(IMAGE_NAME) \
		--platform=linux/amd64,linux/arm64 \
		--label app-name=$(APP_NAME) \
		--label app-version=$(APP_VERSION) \
		--label app-git-version=$(GIT_VERSION) \
		--label app-arch=multiarch \
		--label app-base-image=$(BASE_IMAGE) \
		--label org.opencontainers.image.source=$(APP_REPOSITORY) \
		-f Containerfile .

verify-image:
	$(BUILDAH) images
	$(PODMAN) run $(IMAGE_NAME) /usr/local/src/$(APP_NAME)/shelter.py --version

verify-multiarch-image:
	$(BUILDAH) images
	$(BUILDAH) manifest inspect $(IMAGE_NAME)

push-image:
ifeq ($(CI), true)
	$(BUILDAH) push $(IMAGE_NAME)
endif

push-multiarch-image:
ifeq ($(CI), true)
	$(BUILDAH) manifest push --all $(IMAGE_NAME) docker://$(IMAGE_NAME)
endif

run-container: VERIFY_URL = http://localhost:$(PORT)/{healthcheck,release}
run-container: verify-image
	$(PODMAN) run -d -p $(PORT):$(PORT) $(IMAGE_NAME)
	sleep 10
	$(CURL) -fsS -i -m 10 -w "\n--- %{url_effective} \n" $(VERIFY_URL)
	$(PODMAN) stop -l

image: IMAGE_NAME = $(IMAGE_PREFIX)/$(APP_NAME):$(IMAGE_VERSION)
image: clean prep-version-file build-image verify-image

multiarch-image: IMAGE_NAME = $(IMAGE_PREFIX)/$(APP_NAME):$(IMAGE_VERSION)
multiarch-image: clean prep-version-file build-multiarch-image verify-multiarch-image push-multiarch-image

run-image: IMAGE_NAME = $(IMAGE_PREFIX)/$(APP_NAME):$(IMAGE_VERSION)
run-image: run-container

.PHONY: check check-required check-optional
.PHONY: clean prep-version-file
.PHONY: build-image verify-image push-image image
.PHONY: build-multiarch-image verify-multiarch-image push-multiarch-image multiarch-image
.PHONY: run-image run-container
