PYTHON ?= .venv/bin/python
PIP := $(PYTHON) -m pip
BOOTSTRAP_PYTHON ?=

.PHONY: venv install-dev test clean build

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
	PATH="$(dir $(abspath $(PYTHON))):$$PATH" $(PIP) install --config-settings="build-args=--locked" -e '.[dev]'

install-dev:
	PATH="$(dir $(abspath $(PYTHON))):$$PATH" $(PIP) install --config-settings="build-args=--locked" -e '.[dev]'

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

clean:
	rm -rf build/lib build/bdist.* dist *.egg-info src/*.egg-info

build: clean
	$(PYTHON) -m maturin build --release --locked --sdist --out dist -i "$(abspath $(PYTHON))"
