import decimal
import operator

from thirtyna.core import UsageError, input_value, parser

SWITCH = "-calc"
NAME = "Calculator Agent"
OPS = {"add": operator.add, "sub": operator.sub, "mul": operator.mul,
       "div": operator.truediv}


def run(argv):
    cli = parser(SWITCH, NAME + " performs decimal arithmetic.",
                 "Example: echo '10 20' | 30na -calc -add. Supply two numbers "
                 "as arguments, via stdin, or at the terminal prompt.")
    for op in OPS:
        cli.add_argument("-" + op, nargs="*", metavar="NUMBER")
    args = vars(cli.parse_args(argv))
    selected = [(key, values) for key, values in args.items() if values is not None]
    if not selected:
        raise UsageError("Select an arithmetic operation")
    results = []
    for key, values in selected:
        if not values:
            values = input_value("Two numbers:").split()
        if len(values) != 2:
            raise UsageError("Expected two numbers per operation")
        try:
            a, b = map(decimal.Decimal, values)
            if not a.is_finite() or not b.is_finite():
                raise UsageError("Expected finite numbers")
            if key == "div" and b == 0:
                raise UsageError("Division by zero")
            results.append(OPS[key](a, b))
        except decimal.DecimalException as exc:
            raise UsageError("Invalid or unsupported decimal number") from exc
    for value in results:
        print(value)
