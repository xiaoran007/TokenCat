PYTHON ?= .venv/bin/python
PIP := $(PYTHON) -m pip
BOOTSTRAP_PYTHON ?=
PACKAGE ?= tokencat
TWINE_REPOSITORY ?= pypi

.PHONY: venv install-dev install-release test clean refresh-bundled-pricing build check-dist release-check publish publish-testpypi

venv:
	@if [ ! -x .venv/bin/python ]; then \
		bootstrap_python="$(BOOTSTRAP_PYTHON)"; \
		if [ -z "$$bootstrap_python" ] && [ -n "$$CONDA_PREFIX" ] && [ -x "$$CONDA_PREFIX/bin/python" ]; then \
			bootstrap_python="$$CONDA_PREFIX/bin/python"; \
		fi; \
		if [ -z "$$bootstrap_python" ] && command -v python3 >/dev/null 2>&1; then \
			bootstrap_python="python3"; \
		fi; \
		if [ -z "$$bootstrap_python" ] && command -v python >/dev/null 2>&1; then \
			bootstrap_python="python"; \
		fi; \
		if [ -z "$$bootstrap_python" ]; then \
			echo "No python interpreter found. Install Python 3.9+ first."; \
			exit 1; \
		fi; \
		"$$bootstrap_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || { \
			echo "Python 3.9+ is required to create .venv."; \
			exit 1; \
		}; \
		"$$bootstrap_python" -m venv .venv; \
	fi
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

install-dev:
	$(PIP) install -e '.[dev]'

install-release:
	$(PIP) install -e '.[dev,release]'

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

clean:
	rm -rf build dist *.egg-info

refresh-bundled-pricing:
	$(PYTHON) -m tokencat.core.pricing refresh-bundled

build: clean
	$(PYTHON) -m build

check-dist: build
	$(PYTHON) -m twine check dist/*

release-check: test check-dist

publish: check-dist
	$(PYTHON) -m twine upload --repository $(TWINE_REPOSITORY) dist/*

publish-testpypi: check-dist
	$(PYTHON) -m twine upload --repository testpypi dist/*
