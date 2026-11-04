.PHONY: install lint test bench image up validate crds

IMAGE ?= agent-gateway-stack:dev
KSERVE_REF := v0.21.0
OPENSHIFT_API_REF := e51674a806506ccccf24349bf96cb88a8dbc6ecc
CRDS := .cache/crds

install:
	pip install -e '.[dev]' jsonschema

lint:
	ruff check . && ruff format --check .

test:
	pytest

bench:
	python bench/gateway_overhead.py --requests 1500 --repeats 3

image:
	docker build --build-arg GIT_SHA=$$(git rev-parse --short=12 HEAD) -t $(IMAGE) .

up:
	docker compose up --build

$(CRDS):
	mkdir -p $(CRDS)
	curl -sSfL -o $(CRDS)/inferenceservices.yaml https://raw.githubusercontent.com/kserve/kserve/$(KSERVE_REF)/config/crd/full/serving.kserve.io_inferenceservices.yaml
	curl -sSfL -o $(CRDS)/servingruntimes.yaml https://raw.githubusercontent.com/kserve/kserve/$(KSERVE_REF)/config/crd/full/serving.kserve.io_servingruntimes.yaml
	curl -sSfL -o $(CRDS)/routes.yaml https://raw.githubusercontent.com/openshift/api/$(OPENSHIFT_API_REF)/route/v1/zz_generated.crd-manifests/routes.crd.yaml

crds: $(CRDS)

validate: crds
	kubectl kustomize deploy/overlays/kind | kubeconform -strict -summary -
	kubectl kustomize deploy/overlays/openshift-ai > .cache/openshift-ai.yaml
	kubeconform -strict -ignore-missing-schemas -summary .cache/openshift-ai.yaml
	python scripts/validate_crds.py .cache/openshift-ai.yaml $(CRDS)/*.yaml
