.PHONY: build deploy test lint clean

build:
	sam build

deploy: build
	sam deploy

test:
	PYTHONPATH=src python -m pytest -q

lint:
	python -m compileall -q src tests

clean:
	rm -rf .aws-sam .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
