.PHONY: run test lint format init clean

run:
	python -m src.main

test:
	pytest tests/ -v --tb=short

lint:
	ruff check src/ tests/ --fix
	mypy src/

format:
	ruff format src/ tests/

init:
	python -c "from src.config.settings import settings; print('Config OK:', settings.database.url)"

clean:
	rm -rf data/*.db logs/*.log __pycache__ src/__pycache__
