from typing import Optional
import clicktypes


RESULT = None


@clicktypes.composite(
    required=["a"]
)
class Foo:
    """
    A Foo.

    Args:
        a: blah
        b: blorf
    """
    def __init__(self, a: int, b: str = "foo"):
        self.a = a
        self.b = b

    def __eq__(self, other):
        return self.a == other.a and self.b == other.b

    def __str__(self):
        return "{} {}".format(self.a, self.b)


@clicktypes.command()
def main(foo: Foo, *args, bar: int = 1, baz: Optional[float] = None, **kwargs):
    """Process some metasyntactic variables.

    Args:
        foo: A Foo
        *args: Extra args
        bar: A bar
        baz: A baz
        **kwargs: Extra kwargs
    """
    global RESULT
    RESULT = dict(
        foo=foo,
        args=args,
        bar=bar,
        baz=baz,
        kwargs=kwargs
    )
