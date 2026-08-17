VENV := ./.venv/bin

.PHONY: setup test lint module clean

setup:
	./setup.sh

test:
	$(VENV)/python -m pytest tests/ -q

lint:
	$(VENV)/python -m pip install -q ruff && $(VENV)/python -m ruff check src tests

module: module.tar.gz

module.tar.gz: main.spec src/*.py meta.json models/gesture_recognizer.task
	./build.sh

clean:
	rm -rf build dist module.tar.gz .pytest_cache **/__pycache__
