PYTHON ?= python3
export PYTHON

.PHONY: check fetch build verify

check:
	shellcheck scripts/*.sh
	$(PYTHON) -m ruff format --check scripts
	$(PYTHON) -m ruff check scripts
	$(PYTHON) -m mypy --strict scripts/*.py
	$(PYTHON) -m json.tool locks/inputs.json >/dev/null

fetch:
	mkdir -p out
	flock out/build.lock $(PYTHON) scripts/inputs.py

build:
	mkdir -p out
	flock out/build.lock bash scripts/build.sh

verify:
	flock --shared out/build.lock bash scripts/verify.sh
