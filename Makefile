.PHONY: check

# The checks that must pass before every commit.
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest
