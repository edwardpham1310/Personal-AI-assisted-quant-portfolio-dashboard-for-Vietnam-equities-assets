.PHONY: install install-dev lint format test test-cov clean init-db

install:
	pip install -e .

install-dev:
	pip install -e ".[dev,vnstock]"

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=quant_vn_data --cov-report=term-missing --cov-report=html

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build

init-db:
	quant-vn-data db init

config:
	quant-vn-data config show

quality-report:
	quant-vn-data quality-report --output reports/data_quality_report.csv
