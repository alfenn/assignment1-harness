.PHONY: test test-live test-all costs

test:
	uv run pytest

test-live:
	uv run pytest -m live -s

test-all:
	uv run pytest -m "live or not live" -s

costs:
	uv run python -m cs329z_hw1.llm

chat: 
	uv run python -m cs329z_hw1.chat