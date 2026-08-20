# Common developer tasks for agentic-finance-crew.
# All targets run key-free against the deterministic local engine.

PYTHON ?= python
IMAGE  ?= agentic-finance-crew
PORT   ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install test demo run docker-build docker-run docker-up clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package with dev dependencies
	$(PYTHON) -m pip install -e ".[dev]"

test:  ## Run the full test suite
	$(PYTHON) -m pytest -q

demo:  ## Run the CLI demo over the sample batch
	$(PYTHON) run_demo.py

run:  ## Start the FastAPI service with autoreload
	$(PYTHON) -m uvicorn app:app --reload --port $(PORT)

docker-build:  ## Build the Docker image
	docker build -t $(IMAGE) .

docker-run: docker-build  ## Build and run the image
	docker run --rm -p $(PORT):8000 $(IMAGE)

docker-up:  ## Build and start via docker compose
	docker compose up --build

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
