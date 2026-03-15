PYTHON ?= .venv/bin/python
PIP := $(PYTHON) -m pip
PACKAGE ?= tokencat
TWINE_REPOSITORY ?= pypi

.PHONY: install-dev install-release test clean build check-dist release-check publish publish-testpypi

install-dev:
	$(PIP) install -e '.[dev]'

install-release:
	$(PIP) install -e '.[dev,release]'

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

clean:
	rm -rf build dist *.egg-info

build: clean
	$(PYTHON) -m build

check-dist: build
	$(PYTHON) -m twine check dist/*

release-check: test check-dist

publish: check-dist
	$(PYTHON) -m twine upload --repository $(TWINE_REPOSITORY) dist/*

publish-testpypi: check-dist
	$(PYTHON) -m twine upload --repository testpypi dist/*
