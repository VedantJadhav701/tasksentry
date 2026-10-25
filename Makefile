.PHONY: install test lint format typecheck check benchmark dashboard build clean

install:
	pip install -e ".[dev,dashboard,ollama,openai,benchmark]"

test:
	python -m pytest -q

test-cov:
	python -m pytest --cov=tasksentry --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy src/tasksentry

check: lint typecheck test

benchmark:
	python -m tasksentry.benchmark.runner --suite offline-v0.1 --output reports/offline-benchmark.json

dashboard:
	python -m tasksentry.cli dashboard --host 127.0.0.1 --port 8321

build:
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
