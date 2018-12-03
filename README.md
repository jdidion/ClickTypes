# ClickTypes

ClickTypes creates Click-based CLIs using type annotations.

The simplest use of ClickTypes requires annotating your main method with `@clicktypes.command`:

```python
# test.py
import clicktypes

@clicktypes.command("main")
def main(greeting: str, name: str):
    print(f"{greeting} {name}")

if __name__ == "__main__":
    main()
```

```bash
$ python test.py --help
Usage: test.py [OPTIONS] [GREETING] [NAME]

Options:
  --help  Show this message and exit.
```

## Type conversion

In Click, type conversion can be done either in a callback or by using a callable type (such as a subclass of ParamType) as the type. In ClickTypes, types are defined by type hints. By default, type conversions are performed automatically for Callable types. However, for more complex type conversion, conversion functions are used.

A conversion function

## Conditionals and Validations

Conditionals and Validations are similar - they are both functions that take **kwargs parameter. The keywords are paramter names and values are parameter values. When the function takes multiple parameters, they should specify the order; ordering depends on python 3.5+ behavior that dictionaries are ordered by default.

A conditional function is used to modify the values of one or more parameters conditional on the value(s) of other parameters. A conditional function may return a dict with keys being parameter names that should be updated, and values being the new parameter values.

A validation function is intended to check that one or more paramter values conform to certain restrictions. The return value of a validation function is ignored.

Both conditional and validation functions can throw ValidationError.

These functions can be associated with paramters in two ways. First, using the 'conditionals' and 'validations' arguments of the command decorator. These are dicts with a parameter name or tuple of paramter names being the key and the function being the value. Second, validation functions can be associated with paramters when they are annotated with @validation and the parameter type matches the type argument of the validation decorator. Multi-paramter validations can only be associated via the first method. Since conditionals are expected to be multi-valued, there is no @conditional annotation, i.e. they must always be explicitly specified.

## Type matching

As described above, conversions and validations can be matched to parameters by matching the parameter type to the type argument of the decorator. In addition to built-in and object types, you can also use distinct types created by the typing.NewType function. For example, if you want to define a paramter that must be positive and even:

```
PositiveEven = NewType('PositiveEven', int)

@validation(PositiveEven)
def validate_positive_even(arg: int):
  if i < 0:
    raise ValidationError()
  if i % 2 != 0:
    raise ValidationError()
```

Note that the typing library does not currently provide an intersection type. Thus, Positive, Even, and PositiveEven must all be distinct validations. There are two ways to simplify: 1) add the paramter to the validation dict of the command decorator with a tuple of mutliple functions as the value; 2) create a composite validation:

```
@validation(PositiveEven, (positive, even))
def validate_positive_even(arg: int):
  pass
```

or even

```
validation(PositiveEven, (positive, even))
```


## Details


## Creating entrypoints

* Top-level function
* Add entry point to setup.py or pyproject.toml
* Specify parameter types using type hints
* Specify parameter defaults
* Create function docstring with parameter help messages
* Add command decorator; optionally specify short option names,
  validations, etc.

## Option attribute inference

### All Parameters

* name (long): parameter name; underscores converted to dashes unless keep_underscores=True in the command decorator.
* name (short): starting from the left-most character of the parameter name, the first character that is not used by another parameter or by any built-in; can be overridden by specifying the 'parameter_names' dictionary in the command decorator.
* type: inferred from the type hint; if type hint is missing, inferred from the default value; if default value is missing, str.
* required: by default, true for positional arguments (Arguments) and false for keyword arguments (Options); if positionals_as_options=True in the command decorator, positional arguments are instead required Options. Required keyword arguments can be specified in the 'required' list in the command decorator.
* default: unset for positional arguments, keyword value for keyword arguments.
* nargs: 1 unless type is Tuple (in which case nargs is the number of arguments to the Tuple).

### Option-only

* hide_input: False unless the command 'hidden' parameter is specified and includes the parameter name.
* is_flag: True for keyword arguments of type boolean; assumed to be the True option unless the name starts with 'no'; the other option will always be inferred by adding/removing 'no-'
* multiple: True for sequence types
* help: Parsed from docstring.

## Command line processing

1. Tokenized command line passed to Click
2. Tokens assigned to arguments/options
3. Unrecognized tokens are handled as follows:
   * If the function signature has *args, unrecognized positional arguments are passed, otherwise discarded (unless ignore_unrecognized=False)
   * If the function signature has **kwargs, unrecognized options are passed, otherwise discarded (unless ignore_unrecognized=False)
4. Type conversions
5. Conditionals
6. Validations

## Todo

* Look at incorporating features from contributed packages: https://github.com/click-contrib