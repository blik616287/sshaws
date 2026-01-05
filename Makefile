# sshaws Makefile
#
# Targets:
#   make build      - Build pip package (wheel and sdist)
#   make test       - Run tests with coverage
#   make lint       - Run pylint
#   make install    - Install from source
#   make install-dev - Install in development mode with test deps
#   make deb        - Build Debian package
#   make clean      - Remove build artifacts
#   make all        - Run lint, test, and build
#
# Environment variables:
#   VERSION         - Package version (default: 0.1.0)

PACKAGE_NAME = sshaws
VERSION ?= 0.1.0
PYTHON = python3
PIP = pip3

# Debian package variables
DEB_NAME = $(PACKAGE_NAME)_$(VERSION)_all.deb
DEB_DIR = deb_build

.PHONY: all build test lint install install-dev deb clean help set-version

all: lint test build

help:
	@echo "sshaws build targets:"
	@echo "  make build       - Build pip package (wheel and sdist)"
	@echo "  make test        - Run tests with coverage"
	@echo "  make lint        - Run pylint (must score 10.0/10)"
	@echo "  make install     - Install from source"
	@echo "  make install-dev - Install in development mode with test deps"
	@echo "  make deb         - Build Debian package"
	@echo "  make clean       - Remove build artifacts"
	@echo "  make all         - Run lint, test, and build"
	@echo "  make set-version - Update version in source files"
	@echo ""
	@echo "Environment variables:"
	@echo "  VERSION          - Package version (default: 0.1.0, current: $(VERSION))"

build:
	$(PYTHON) -m build

test:
	$(PYTHON) -m pytest -v

lint:
	pylint src/sshaws/

install:
	$(PIP) install .

install-dev:
	$(PIP) install -e ".[test]"

uninstall:
	$(PIP) uninstall -y $(PACKAGE_NAME)

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf $(DEB_DIR)/
	rm -f *.deb
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Debian package build
deb: build
	@echo "Building Debian package..."
	rm -rf $(DEB_DIR)
	mkdir -p $(DEB_DIR)/DEBIAN
	mkdir -p $(DEB_DIR)/usr/lib/python3/dist-packages
	mkdir -p $(DEB_DIR)/usr/bin

	# Copy package files
	cp -r src/sshaws $(DEB_DIR)/usr/lib/python3/dist-packages/

	# Create executable wrapper
	echo '#!/usr/bin/env python3' > $(DEB_DIR)/usr/bin/sshaws
	echo 'from sshaws.cli import main' >> $(DEB_DIR)/usr/bin/sshaws
	echo 'import sys' >> $(DEB_DIR)/usr/bin/sshaws
	echo 'sys.exit(main())' >> $(DEB_DIR)/usr/bin/sshaws
	chmod 755 $(DEB_DIR)/usr/bin/sshaws

	# Create control file
	echo "Package: $(PACKAGE_NAME)" > $(DEB_DIR)/DEBIAN/control
	echo "Version: $(VERSION)" >> $(DEB_DIR)/DEBIAN/control
	echo "Section: utils" >> $(DEB_DIR)/DEBIAN/control
	echo "Priority: optional" >> $(DEB_DIR)/DEBIAN/control
	echo "Architecture: all" >> $(DEB_DIR)/DEBIAN/control
	echo "Depends: python3, python3-boto3, awscli, session-manager-plugin" >> $(DEB_DIR)/DEBIAN/control
	echo "Maintainer: sshaws maintainers" >> $(DEB_DIR)/DEBIAN/control
	echo "Description: SSH to private AWS EC2 instances via SSM" >> $(DEB_DIR)/DEBIAN/control
	echo " A drop-in SSH replacement for connecting to private EC2 instances" >> $(DEB_DIR)/DEBIAN/control
	echo " through AWS Systems Manager (SSM). Supports port forwarding," >> $(DEB_DIR)/DEBIAN/control
	echo " identity files, and all standard SSH options." >> $(DEB_DIR)/DEBIAN/control

	# Build the deb
	dpkg-deb --build $(DEB_DIR) $(DEB_NAME)
	@echo "Built: $(DEB_NAME)"

# Update version in source files
set-version:
	@echo "Setting version to $(VERSION)"
	sed -i 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml
	sed -i 's/^__version__ = ".*"/__version__ = "$(VERSION)"/' src/sshaws/__init__.py
	@echo "Updated pyproject.toml and src/sshaws/__init__.py"

# Development helpers
check: lint test

format:
	@echo "No formatter configured. Consider adding black or ruff."

.DEFAULT_GOAL := help
