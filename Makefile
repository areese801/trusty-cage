.PHONY: help build publish publish-test tag lint format test clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

build: clean ## Build wheel and sdist
	python -m build

publish: build ## Build, upload to PyPI, and push a v<version> git tag
	. ./set_creds.sh && twine upload dist/*
	$(MAKE) tag

publish-test: build ## Build and upload to TestPyPI (no tag)
	. ./set_creds.sh && twine upload --repository testpypi dist/*

tag: ## Create and push a v<version> git tag from pyproject.toml
	@VERSION=$$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2); \
	 if git rev-parse "v$$VERSION" >/dev/null 2>&1; then \
	   echo "Tag v$$VERSION already exists — skipping."; \
	 else \
	   git tag -a "v$$VERSION" -m "Release v$$VERSION" && \
	   git push origin "v$$VERSION" && \
	   echo "Tagged and pushed v$$VERSION."; \
	 fi

lint: ## Run ruff check
	ruff check .

format: ## Run ruff format
	ruff format .

test: ## Run pytest
	pytest -q

clean: ## Remove build artifacts
	rm -rf dist/ build/ src/*.egg-info
