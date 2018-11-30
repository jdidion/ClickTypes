import collections
import inspect
from inspect import Parameter
import logging
import re
import typing
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Type, Union, cast

import click
import docparse


LOG = logging.getLogger("ClickTypes")
UNDERSCORES = re.compile("_")


class SignatureError(Exception):
    """Raised when the signature of the decorated method is not supported."""
    pass


class ValidationError(Exception):
    """Raised by a validation function when an input violates a constraint."""
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
        cls: The class being decorated.
        command_kwargs: Keyword arguments to CommandBuilder.
    """
    def __init__(self, cls, command_kwargs):
        self.cls = cls
        self.command_kwargs = command_kwargs

    def handle_args(self, param, ctx):
        pass


class CommandMixin:
    def __init__(
        self,
        *args,
        conditionals: Dict[Sequence[str], Sequence[Callable]],
        validations: Dict[Sequence[str], Sequence[Callable]],
        composites: Dict[str, CompositeParameter],
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
                        (param, ctx.params.get(param, None))
                        for param in params
                    )
                    for fn in fns:
                        result = fn(**fn_kwargs)
                        if result and update:
                            for param, value in result.items():
                                ctx.params[param] = value

        _apply(self.conditionals, update=True)
        _apply(self.validations, update=False)

        if self.composites:
            for param, handler in self.composites.items():
                handler.handle_args(param, ctx)

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


def composite(*args, **kwargs):
    cls = args[0]
    composite_param = CompositeParameter(cls, kwargs)
    COMPOSITES[cls] = composite_param
    return cls


def composite_fn(match_type: Type, **kwargs) -> Callable[[Callable], Callable]:
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
) -> Callable[[Callable], click.Command]:
    """Creates a new :class:`Command` and uses the decorated function as
    callback. Uses type arguments of decorated function to automatically
    create:func:`option`\s and :func:`argument`\s. The name of the command
    defaults to the name of the function.

    Args:

    """
    def decorator(f):
        command_builder = CommandBuilder(name, f, **kwargs)
        return command_builder.click_command

    return decorator


class CommandBuilder:
    def __init__(
        self,
        name,
        f,
        short_names: Optional[Dict[str, str]] = None,
        types: Optional[Dict[str, Callable]] = None,
        required: Optional[Sequence[str]] = None,
        hidden: Optional[Sequence[str]] = None,
        conditionals: Dict[
            Union[str, Tuple[str]], Union[Callable, List[Callable]]] = None,
        validations: Dict[
            Union[str, Tuple[str]], Union[Callable, List[Callable]]] = None,
        keep_underscores: bool = True,
        positionals_as_options: bool = False,
        infer_short_names: bool = True,
        show_defaults: bool = False,
        command_class: Type[click.Command] = ClickTypesCommand,
        option_class: Type[click.Option] = click.Option,
        argument_class: Type[click.Argument] = click.Argument,
        **kwargs
    ):
        self.name = name

        _required = set()
        if required:
            _required.update(required)

        if conditionals is None:
            _conditionals = {}
        else:
            _conditionals = dict(
                (
                    k if isinstance(k, tuple) else (k,),
                    list(v) if v and not isinstance(v, list) else v
                )
                for k, v in conditionals.items()
            )

        if validations is None:
            _validations = {}
        else:
            _validations = dict(
                (
                    k if isinstance(k, tuple) else (k,),
                    list(v) if v and not isinstance(v, list) else v
                )
                for k, v in validations.items()
            )

        function_name = f.__name__
        signature = inspect.signature(f)
        docs = docparse.parse_docs(f, docparse.DocStyle.GOOGLE)

        self.click_command = command_class(
            name or function_name.lower().replace('_', '-'),
            help=docs.description,
            callback=f,
            **kwargs
        )
        if isinstance(self.click_command, CommandMixin):
            cast(CommandMixin, self.click_command).conditionals = _conditionals
            cast(CommandMixin, self.click_command).validations = _validations
        else:
            LOG.warning(
                f"Command {command_class} is not a subclass of CommandMixin; "
                f"conditionals and validations will not be applied."
            )

        param_help = dict((p.name, p.description) for p in docs.parameters.values())
        used_short_names = set()

        for param_name, param in signature.parameters.items():
            if param.kind is Parameter.VAR_POSITIONAL:
                self.click_command.allow_extra_arguments = True
                continue
            elif param.kind is Parameter.VAR_KEYWORD:
                self.click_command.ignore_unknown_options = False
                continue

            if keep_underscores:
                long_name = param_name
            else:
                long_name = UNDERSCORES.sub("-", param_name)

            param_type = param.annotation
            param_default = param.default
            has_default = param.default not in {Parameter.empty, None}
            param_optional = has_default

            if param_type in COMPOSITES:
                complex_fn = COMPOSITES[param_type]
                complex_fn(param_name, param, command)

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

                if param_type is Parameter.empty:
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
                            f"{param_name} in function {function_name}"
                        )

                # Resolve Union attributes
                # The only time a Union type is allowed is when it has two args and
                # one is None (i.e. an Optional)
                if (
                    hasattr(param_type, "__origin__") and
                    param_type.__origin__ is Union
                ):
                    filtered_args = set(filter(None, param_type.__args__))
                    if len(filtered_args) == 1:
                        param_type = filtered_args.pop()
                        param_optional = True
                    else:
                        raise SignatureError(
                            f"Union type not supported for parameter {param_name} "
                            f"in function {function_name}"
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
                    if param_name not in _validations:
                        _validations[param_name] = []
                    _validations[param_name].extend(VALIDATIONS[match_type])

            is_option = param_optional or positionals_as_options

            if is_option:
                short_name = None
                if short_names and param_name in short_names:
                    short_name = short_names[param_name]
                elif infer_short_names:
                    for char in param_name:
                        if char.isalpha():
                            if char.lower() not in used_short_names:
                                short_name = char.lower()
                            elif char.upper() not in used_short_names:
                                short_name = char.upper()
                            else:
                                continue
                            used_short_names.add(short_name)
                            break
                    else:
                        raise click.BadParameter(
                            f"Could not infer short name for parameter {param_name}"
                        )

                if not is_flag:
                    long_name_str = f"--{long_name}"
                elif long_name.startswith("no-"):
                    long_name_str = f"--{long_name[3:]}/--{long_name}"
                else:
                    long_name_str = f"--{long_name}/--no-{long_name}"
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
                    help=param_help[param_name]
                )
            else:
                param = argument_class(
                    [long_name],
                    type=click_type,
                    default=param_default,
                    show_default=show_defaults,
                    nargs=-1 if param_nargs == 1 and param_multiple else param_nargs,
                    help=param_help[param_name]
                )

            self.click_command.params.append(param)
