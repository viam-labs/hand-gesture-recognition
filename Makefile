VENV := ./.venv/bin

.PHONY: setup test lint module clean

setup:
	./setup.sh

test:
	$(VENV)/python -m pytest tests/ -q

lint:
	$(VENV)/ruff check src tests main.py

module: module.tar.gz

module.tar.gz: main.spec src/*.py meta.json models/gesture_recognizer.task
	./build.sh

clean:
	rm -rf build dist module.tar.gz .pytest_cache **/__pycache__
