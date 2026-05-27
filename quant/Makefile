.PHONY: install dev-install test lint format type-check clean run-example

install:
	pip install -e .

dev-install:
	pip install -e ".[dev,vnstock]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=src/quant_vn --cov-report=html --cov-report=term-missing

lint:
	ruff check src/ tests/

format:
	black src/ tests/ examples/
	ruff check --fix src/ tests/

type-check:
	mypy src/quant_vn/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage

run-example:
	python examples/run_backtest_fpt.py

db-init:
	quant-vn db-init

# Quick backtest on FPT (requires data in data/raw/)
backtest-fpt:
	quant-vn backtest --strategy ma_cross --symbol FPT --start 2020-01-01 --end 2024-12-31
