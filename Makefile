.PHONY: test test-live test-all

test:
	uv run pytest

test-live:
	uv run pytest -m live -s

test-all:
	uv run pytest -m "live or not live" -s
