"""Problem 5 (tool_registry): hold tools, validate calls, run them safely."""

from __future__ import annotations

from typing import Optional

from jsonschema import Draft202012Validator

from cs329z_hw1.types import ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec] = ()):
        self._tools: dict[str, ToolSpec] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool
        self._validators[tool.name] = Draft202012Validator(tool.parameters)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    def validate(self, name: str, args: dict) -> Optional[ToolResult]:
        """The unknown_tool / invalid_args result execute would give, or None."""
        try:
            if name not in self._tools:
                available = ", ".join(self._tools) or "(none)"
                return ToolResult(
                    "unknown_tool", f"Unknown tool {name!r}. Available tools: {available}."
                )
            if not isinstance(args, dict):
                return ToolResult(
                    "invalid_args",
                    f"Arguments for {name!r} must be a JSON object, got {type(args).__name__}.",
                )
            errors = sorted(self._validators[name].iter_errors(args), key=lambda e: list(e.path))
            if errors:
                lines = []
                for err in errors:
                    where = "/".join(str(p) for p in err.path) or "(arguments)"
                    lines.append(f"- {where}: {err.message}")
                return ToolResult(
                    "invalid_args", f"Invalid arguments for {name!r}:\n" + "\n".join(lines)
                )
            return None
        except Exception as exc:  # a broken schema must not crash the agent
            return ToolResult("invalid_args", f"Could not validate arguments for {name!r}: {exc}")

    def execute(self, name: str, args: dict) -> ToolResult:
        rejected = self.validate(name, args)
        if rejected is not None:
            return rejected
        try:
            value = self._tools[name].fn(**args)
            return ToolResult("ok", str(value))
        except Exception as exc:
            return ToolResult("tool_error", f"Tool {name!r} raised {type(exc).__name__}: {exc}")
