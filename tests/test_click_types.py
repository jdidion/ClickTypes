import sys
import unittest
import tests.simple


class SimpleTest(unittest.TestCase):
    def test_simple(self):
        sys.argv = ["main", "1"]
        try:
            tests.simple.main()
        except SystemExit:
            pass
        expected = dict(
            foo=tests.simple.Foo(1),
            args=(),
            bar=1,
            baz=None,
            kwargs={}
        )
        assert tests.simple.RESULT == expected
