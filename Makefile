PYTHON ?= .venv/bin/python
PIP := $(PYTHON) -m pip
PACKAGE ?= tokencat
TWINE_REPOSITORY ?= pypi
MACOS_PROJECT := macos/TokenCatMac/TokenCatMac.xcodeproj
MACOS_SCHEME := TokenCatMac
MACOS_DERIVED_DATA := build/macos-derived
DEVELOPER_DIR ?= /Applications/Xcode.app/Contents/Developer
MACOS_XCODEBUILD := xcodebuild -project $(MACOS_PROJECT) -scheme $(MACOS_SCHEME) -derivedDataPath $(MACOS_DERIVED_DATA)
ifdef TOKENCAT_DEVELOPMENT_TEAM
MACOS_XCODEBUILD += DEVELOPMENT_TEAM=$(TOKENCAT_DEVELOPMENT_TEAM)
endif
export DEVELOPER_DIR

.PHONY: install-dev install-release test clean refresh-bundled-pricing build check-dist release-check publish publish-testpypi macos-build macos-run macos-test macos-clean test-all

install-dev:
	$(PIP) install -e '.[dev]'

install-release:
	$(PIP) install -e '.[dev,release]'

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

clean:
	rm -rf build dist *.egg-info

macos-build:
	$(MACOS_XCODEBUILD) -configuration Debug build

macos-run:
	./script/build_and_run.sh

macos-test:
	$(MACOS_XCODEBUILD) -configuration Debug -destination 'platform=macOS' test

macos-clean:
	rm -rf $(MACOS_DERIVED_DATA)

test-all: test macos-test

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
