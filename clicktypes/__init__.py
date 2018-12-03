from abc import ABCMeta, abstractmethod
import collections
import copy
import inspect
import logging
import re
import typing
from typing import (
    Callable, Dict, List, Optional, Sequence, Set, Tuple, Type, Union
)

import click
import docparse


LOG = logging.getLogger("ClickTypes")
UNDERSCORES = re.compile("_")
ALPHA_CHARS = set(chr(i) for i in tuple(range(97, 123)) + tuple(range(65, 91)))


class SignatureError(Exception):
    """Raised when the signature of the decorated method is not supported."""
    pass


class ValidationError(Exception):
    """Raised by a validation function when an input violates a constraint."""
    pass


class ParameterCollisionError(Exception):
    """Raised when a composite paramter has the same name as one in the parent
    function.
    """
    pass


class CompositeParameter:
    """
    Represents a complex type that requires values from multiple parameters. A
    composite parameter is defined by annotating a class using the `composite`
    decorator. The parameters of the class' construtor (exluding `self`) are
    added to the CommandBuilder, prior to parsing, and then they are replaced by
    an instance of the annotated class after parsing.

    Note that composite parameters cannot be nested, i.e. a parameter cannot be a
    list of composite types, and a composite type cannot itself have composite type
    parameters - either of these will cause a `SignatureError` to be raised.

    Args:
        cls_or_fn: The class being decorated.
        command_kwargs: Keyword arguments to CommandBuilder.
    """
    def __init__(self, cls_or_fn: Callable, command_kwargs: dict):
        self._cls_or_fn = cls_or_fn
        self._command_kwargs = command_kwargs

    def __call__(
        self, param_name: str, click_command: "ClickTypesCommand",
        exclude_short_names:  Set[str]
    ):
        kwargs = copy.copy(self._command_kwargs)
        if "exclude_short_names" in kwargs:
            exclude_short_names.update(kwargs["exclude_short_names"])
        kwargs["exclude_short_names"] = exclude_short_names
        return CompositeBuilder(self._cls_or_fn, param_name, click_command, **kwargs)


class CommandMixin:
    def __init__(
        self,
        *args,
        conditionals: Dict[Sequence[str], Sequence[Callable]],
        validations: Dict[Sequence[str], Sequence[Callable]],
        composites: Dict[str, "CompositeBuilder"],
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.conditionals = conditionals
        self.validations = validations
        self.composites = composites

    def parse_args(self, ctx, args):
        args = super().parse_args(ctx, args)

        def _apply(l, update=False):
            if l:
                for params, fns in l.items():
                    fn_kwargs = dict(
                        (_param, ctx.params.get(_param, None))
                        for _param in params
                    )
                    for fn in fns:
                        result = fn(**fn_kwargs)
                        if result and update:
                            for _param, value in result.items():
                                ctx.params[_param] = value

        _apply(self.conditionals, update=True)
        _apply(self.validations, update=False)

        if self.composites:
            for handler in self.composites.values():
                handler.handle_args(ctx)

        return args


class ClickTypesCommand(CommandMixin, click.Command):
    pass


class WrapperType(click.ParamType):
    def __init__(self, name, fn):
        self.name = name
        self.fn = fn

    def convert(self, value, param, ctx):
        return self.fn(value, param, ctx)


CONVERSIONS: Dict[Type, click.ParamType] = {}
VALIDATIONS: Dict[Type, List[Callable]] = {}
COMPOSITES: Dict[Type, CompositeParameter] = {}


def conversion(dest_type):
    def decorator(f: Callable) -> Callable:
        click_type = WrapperType(dest_type.__name__, f)
        CONVERSIONS[dest_type] = click_type
        return f

    return decorator


def composite(**kwargs):
    def decorator(cls):
        composite_param = CompositeParameter(cls, kwargs)
        COMPOSITES[cls] = composite_param
        return cls

    return decorator


def composite_factory(match_type: Type, **kwargs) -> Callable[[Callable], Callable]:
    def decorator(f):
        composite_param = CompositeParameter(f, kwargs)
        COMPOSITES[match_type] = composite_param
        return f

    return decorator


def validation(match_type: Type) -> Callable[[Callable], Callable]:
    def decorator(f: Callable) -> Callable:
        if match_type not in VALIDATIONS:
            VALIDATIONS[match_type] = []
        VALIDATIONS[match_type].append(f)
        return f

    return decorator


def command(
    name: Optional[str] = None,
    **kwargs
) -> Callable[[Callable], ClickTypesCommand]:
    """Creates a new :class:`Command` and uses the decorated function as
    callback. Uses type arguments of decorated function to automatically
    create:func:`option`\s and :func:`argument`\s. The name of the command
    defaults to the name of the function.

    Args:

    """
    def decorator(f):
        command_builder = CommandBuilder(f, name, **kwargs)
        return command_builder.command

    return decorator


class ParamBuilder(metaclass=ABCMeta):
    def __init__(
        self,
        to_wrap: Callable,
        func_params: Optional[Dict[str, inspect.Parameter]] = None,
        option_order: Optional[Sequence[str]] = None,
        exclude_short_names: Optional[Set[str]] = None,
        required: Optional[Sequence[str]] = None,
        conditionals: Dict[
            Union[str, Tuple[str, ...]], Union[Callable, List[Callable]]] = None,
        validations: Dict[
            Union[str, Tuple[str, ...]], Union[Callable, List[Callable]]] = None,
        **kwargs
    ):
        self._wrapped = to_wrap
        self._wrapped_name = to_wrap.__name__
        if func_params is None:
            func_params = inspect.signature(to_wrap).parameters
        self._func_params = func_params
        self._docs = docparse.parse_docs(to_wrap, docparse.DocStyle.GOOGLE)
        self._has_order = option_order is not None
        self.option_order = option_order or []
        if exclude_short_names is None:
            exclude_short_names = set()
        self._exclude_short_names = exclude_short_names

        self.required = set()
        if required:
            self.required.update(required)

        if conditionals is None:
            self.conditionals = {}
        else:
            self.conditionals = dict(
                (
                    k if isinstance(k, tuple) else (k,),
                    list(v) if v and not isinstance(v, list) else v
                )
                for k, v in conditionals.items()
            )

        if validations is None:
            self.validations = {}
        else:
            self.validations = dict(
                (
                    k if isinstance(k, tuple) else (k,),
                    list(v) if v and not isinstance(v, list) else v
                )
                for k, v in validations.items()
            )

        self.params = {}
        self.handle_params(**kwargs)

    @property
    @abstractmethod
    def command(self) -> ClickTypesCommand:
        pass

    @property
    def supports_composites(self) -> bool:
        return False

    def _get_long_name(self, param_name: str, keep_underscores: bool) -> str:
        if keep_underscores:
            return param_name
        else:
            return UNDERSCORES.sub("-", param_name)

    def handle_params(
        self,
        short_names: Optional[Dict[str, str]] = None,
        types: Optional[Dict[str, Callable]] = None,
        hidden: Optional[Sequence[str]] = None,
        keep_underscores: bool = True,
        positionals_as_options: bool = False,
        infer_short_names: bool = True,
        show_defaults: bool = False,
        option_class: Type[click.Option] = click.Option,
        argument_class: Type[click.Argument] = click.Argument,
    ):
        if short_names:
            for short_name in short_names.keys():
                if short_name in self._exclude_short_names:
                    raise ParameterCollisionError(
                        f"Short name {short_name} defined for two different parameters"
                    )
                self._exclude_short_names.add(short_name)

        param_help = {}
        if self._docs:
            param_help = dict(
                (p.name, str(p.description))
                for p in self._docs.parameters.values()
            )

        for param_name, param in self._func_params.items():
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                self.command.allow_extra_arguments = True
                continue
            elif param.kind is inspect.Parameter.VAR_KEYWORD:
                self.command.ignore_unknown_options = False
                continue

            param_long_name = self._get_long_name(param_name, keep_underscores)
            param_type = param.annotation
            param_default = param.default
            has_default = param.default not in {inspect.Parameter.empty, None}
            param_optional = has_default

            if not self._has_order:
                self.option_order.append(param_name)

            if self.supports_composites and param_type in COMPOSITES:
                composite_param = COMPOSITES[param_type]
                builder = composite_param(
                    param_name, self.command, self._exclude_short_names
                )
                self.composites[param_name] = builder
                continue

            param_nargs = 1
            param_multiple = False

            if types and param_name in types:
                click_type = types[param_name]
                is_flag = (
                    click_type == bool or
                    isinstance(click_type, click.types.BoolParamType)
                )
                if isinstance(click_type, click.Tuple):
                    param_nargs = len(click_type.types)

            else:
                click_type = None
                match_type = None

                if param_type is inspect.Parameter.empty:
                    if not has_default:
                        LOG.debug(
                            f"No type annotation or default value for paramter "
                            f"{param_name}; using <str>"
                        )
                        param_type = str
                    else:
                        param_type = type(param_default)
                        LOG.debug(
                            f"Inferring type {param_type} from paramter {param_name} "
                            f"default value {param_default}"
                        )
                elif isinstance(param_type, str):
                    if param_type in globals():
                        param_type = globals()[param_type]
                    else:
                        raise SignatureError(
                            f"Could not resolve type {param_type} of paramter "
                            f"{param_name} in function {self._wrapped_name}"
                        )

                # Resolve Union attributes
                # The only time a Union type is allowed is when it has two args and
                # one is None (i.e. an Optional)
                if (
                    hasattr(param_type, "__origin__") and
                    param_type.__origin__ is Union
                ):
                    filtered_args = set(param_type.__args__)
                    if type(None) in filtered_args:
                        filtered_args.remove(type(None))
                    if len(filtered_args) == 1:
                        param_type = filtered_args.pop()
                        param_optional = True
                    else:
                        raise SignatureError(
                            f"Union type not supported for parameter {param_name} "
                            f"in function {self._wrapped_name}"
                        )

                # Resolve NewType
                if (
                    inspect.isfunction(param_type) and
                    hasattr(param_type, "__supertype__")
                ):
                    # It's a NewType
                    match_type = param_type
                    # TODO: this won't work for nested type hierarchies
                    param_type = param_type.__supertype__

                # Resolve Tuples with specified arguments
                if (
                    isinstance(param_type, typing.TupleMeta) and
                    param_type.__args__
                ):
                    param_nargs = len(param_type.__args__)
                    click_type = click.Tuple(param_type.__args__)

                # Unwrap complex types
                while (
                    isinstance(param_type, typing.TypingMeta) and
                    hasattr(param_type, '__extra__')
                ):
                    param_type = param_type.__extra__

                # Now param_type should be primitive or an instantiable type

                # Allow multiple values when type is a non-string collection
                if (
                    param_nargs == 1 and
                    param_type != str and
                    issubclass(param_type, collections.Collection)
                ):
                    param_multiple = True

                is_flag = param_type == bool

                if click_type is None:
                    # Find type conversion
                    if match_type is None:
                        match_type = param_type
                    if match_type in CONVERSIONS:
                        click_type = CONVERSIONS[match_type]
                    else:
                        click_type = param_type

                # Find validations
                if param_type in VALIDATIONS:
                    if param_name not in self.validations:
                        self.validations[param_name] = []
                        self.validations[param_name].extend(VALIDATIONS[match_type])

            is_option = param_optional or positionals_as_options

            if is_option:
                short_name = None
                if short_names and param_name in short_names:
                    short_name = short_names[param_name]
                elif infer_short_names:
                    for char in param_name:
                        if char.isalpha():
                            if char.lower() not in self._exclude_short_names:
                                short_name = char.lower()
                            elif char.upper() not in self._exclude_short_names:
                                short_name = char.upper()
                            else:
                                continue
                            break
                    else:
                        # try to select one randomly
                        remaining = ALPHA_CHARS - self._exclude_short_names
                        if len(remaining) == 0:
                            raise click.BadParameter(
                                f"Could not infer short name for parameter {param_name}"
                            )
                        # TODO: this may not be deterministic
                        short_name = remaining.pop()

                    self._exclude_short_names.add(short_name)

                if not is_flag:
                    long_name_str = f"--{param_long_name}"
                elif param_long_name.startswith("no-"):
                    long_name_str = f"--{param_long_name[3:]}/--{param_long_name}"
                else:
                    long_name_str = f"--{param_long_name}/--no-{param_long_name}"
                param_decls = [long_name_str]
                if short_name:
                    param_decls.append(f"-{short_name}")

                param = option_class(
                    param_decls,
                    type=click_type,
                    required=not param_optional,
                    default=param_default,
                    show_default=show_defaults,
                    nargs=param_nargs,
                    hide_input=hidden and param_name in hidden,
                    is_flag=is_flag,
                    multiple=param_multiple,
                    help=param_help.get(param_name, None)
                )
            else:
                param = argument_class(
                    [param_long_name],
                    type=click_type,
                    default=param_default,
                    nargs=-1 if param_nargs == 1 and param_multiple else param_nargs
                )
                # TODO: where to show parameter help?
                # help = param_help.get(param_name, None)

            self.params[param_name] = param


class CompositeBuilder(ParamBuilder):
    def __init__(
        self,
        to_wrap: Callable,
        param_name: str,
        click_command: ClickTypesCommand,
        **kwargs
    ):
        self.param_name = param_name
        self._click_command = click_command
        func_params = None
        if inspect.isclass(to_wrap):
            func_params = dict(inspect.signature(to_wrap.__init__).parameters)
            func_params.pop("self")
        super().__init__(to_wrap, func_params, **kwargs)

    @property
    def command(self) -> ClickTypesCommand:
        return self._click_command

    def _get_long_name(self, param_name: str, keep_underscores: bool) -> str:
        return super()._get_long_name(
            "{}_{}".format(self.param_name, param_name),
            keep_underscores
        )

    def handle_args(self, ctx):
        """
        Pop the args added by the composite and replace them with the composite type.

        Args:
            ctx:
        """
        kwargs = {}
        for composite_param_name in self.params.keys():
            arg_name = self._get_long_name(composite_param_name, True)
            kwargs[composite_param_name] = ctx.params.pop(arg_name, None)
        ctx.params[self.param_name] = self._wrapped(**kwargs)


class CommandBuilder(ParamBuilder):
    def __init__(
        self,
        to_wrap: Callable,
        name: Optional[str] = None,
        command_class: Type[ClickTypesCommand] = ClickTypesCommand,
        **kwargs
    ):
        self._name = name
        self._command_class = command_class
        self._click_command = None
        self.composites = {}
        super().__init__(to_wrap, **kwargs)

    @property
    def name(self) -> str:
        return self._name or self._wrapped_name.lower().replace('_', '-')

    @property
    def command(self) -> ClickTypesCommand:
        return self._click_command

    @property
    def supports_composites(self) -> bool:
        return True

    def handle_params(self, **kwargs):
        self._click_command = self._command_class(
            self.name,
            help=str(self._docs.description),
            callback=self._wrapped,
            conditionals=self.conditionals,
            validations=self.validations,
            composites=self.composites,
            **kwargs
        )
        super().handle_params(**kwargs)
        for param_name in self.option_order:
            if param_name in self.composites:
                builder = self.composites[param_name]
                for composite_param_name in builder.option_order:
                    self.command.params.append(builder.params[composite_param_name])
            else:
                self.command.params.append(self.params[param_name])
