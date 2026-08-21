from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


OptionKind = Literal["flag", "value", "optional_value", "int"]
Runner = Callable[[list[str]], int]


class ToolValidationError(ValueError):
    """A tool invocation did not match its registered interface."""


@dataclass(frozen=True)
class ToolArgument:
    name: str
    help: str = ""
    required: bool = False
    multiple: bool = False
    default: str | None = None
    emit_default_with_options: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "help": self.help,
            "required": self.required,
            "multiple": self.multiple,
            "default": self.default,
        }


@dataclass(frozen=True)
class ToolOption:
    name: str
    flag: str
    kind: OptionKind
    help: str = ""
    metavar: str | None = None
    default: Any = None
    secret: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "flag": self.flag,
            "kind": self.kind,
            "help": self.help,
            "metavar": self.metavar,
            "default": self.default,
            "secret": self.secret,
        }


@dataclass(frozen=True)
class ToolSpec:
    id: str
    title: str
    description: str
    runner: Runner
    arguments: tuple[ToolArgument, ...] = field(default_factory=tuple)
    options: tuple[ToolOption, ...] = field(default_factory=tuple)
    mutates: bool = False
    long_running: bool = False
    gui_visible: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "arguments": [arg.as_dict() for arg in self.arguments],
            "options": [opt.as_dict() for opt in self.options],
            "mutates": self.mutates,
            "long_running": self.long_running,
        }

    def build_argv(
        self,
        *,
        arguments: list[str] | tuple[str, ...] | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[str]:
        args = [str(arg) for arg in (arguments or [])]
        opts = options or {}
        by_name = {option.name: option for option in self.options}
        unknown = sorted(set(opts) - set(by_name))
        if unknown:
            label = "option" if len(unknown) == 1 else "options"
            raise ToolValidationError(
                f"{self.id}: unknown {label}: {', '.join(unknown)}"
            )

        argv = self._argument_argv(args, opts)
        for option in self.options:
            if option.name not in opts:
                value = option.default
            else:
                value = opts[option.name]
            argv.extend(self._option_argv(option, value))
        return argv

    def invoke_argv(self, argv: list[str]) -> int:
        return int(self.runner(argv))

    def run(
        self,
        *,
        arguments: list[str] | tuple[str, ...] | None = None,
        options: dict[str, Any] | None = None,
    ) -> int:
        return self.invoke_argv(self.build_argv(arguments=arguments, options=options))

    def _argument_argv(self, args: list[str], options: dict[str, Any]) -> list[str]:
        if not self.arguments:
            if args:
                raise ToolValidationError(f"{self.id}: does not accept arguments")
            return []

        spec = self.arguments[0]
        if len(self.arguments) > 1:
            raise ToolValidationError(f"{self.id}: registry supports one argument group")

        if spec.multiple:
            return args

        if len(args) > 1:
            raise ToolValidationError(f"{self.id}: accepts at most one {spec.name}")
        if args:
            return args
        if spec.required:
            raise ToolValidationError(f"{self.id}: missing required {spec.name}")
        if spec.default is not None and spec.emit_default_with_options and any(
            self._option_is_set(option, options.get(option.name, option.default))
            for option in self.options
        ):
            return [spec.default]
        return []

    def _option_argv(self, option: ToolOption, value: Any) -> list[str]:
        if option.kind == "flag":
            if value in (False, None):
                return []
            if value is not True:
                raise ToolValidationError(f"{self.id}: {option.name} must be true or false")
            return [option.flag]

        if option.kind == "value":
            if value in (None, ""):
                return []
            return [option.flag, str(value)]

        if option.kind == "optional_value":
            if value in (None, False, ""):
                return []
            if value is True:
                return [option.flag]
            return [option.flag, str(value)]

        if option.kind == "int":
            if value in (None, ""):
                return []
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ToolValidationError(
                    f"{self.id}: {option.name} must be an integer"
                ) from exc
            if number < 0 or number > 65535:
                raise ToolValidationError(
                    f"{self.id}: {option.name} must be between 0 and 65535"
                )
            return [option.flag, str(number)]

        raise ToolValidationError(f"{self.id}: unsupported option kind {option.kind}")

    def _option_is_set(self, option: ToolOption, value: Any) -> bool:
        if option.kind == "flag":
            return value is True
        return value not in (None, False, "")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.id in self._tools:
            raise ValueError(f"tool already registered: {spec.id}")
        self._tools[spec.id] = spec
        return spec

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def all(self, *, gui_visible: bool | None = None) -> list[ToolSpec]:
        tools = sorted(self._tools.values(), key=lambda tool: tool.id)
        if gui_visible is None:
            return tools
        return [tool for tool in tools if tool.gui_visible is gui_visible]

    def as_dicts(self, *, gui_visible: bool | None = None) -> list[dict[str, Any]]:
        return [tool.as_dict() for tool in self.all(gui_visible=gui_visible)]
