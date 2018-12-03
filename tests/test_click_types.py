from typing import Optional
import clicktypes


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
    print(foo)
    print(args)
    print(bar)
    print(baz)
    print(kwargs)


if __name__ == "__main__":
    main()
