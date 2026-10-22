.PHONY: test test-live

test:
	uv run pytest

test-live:
	uv run pytest -m live -s
