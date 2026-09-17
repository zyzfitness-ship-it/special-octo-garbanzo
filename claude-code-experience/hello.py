"""A tiny playground script — edit it, break it, ask me to fix it."""


def greet(name: str) -> str:
    return f"Hello, {name}! Claude Code is running in this folder."


def fizzbuzz(n: int) -> list[str]:
    out = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            out.append("FizzBuzz")
        elif i % 3 == 0:
            out.append("Fizz")
        elif i % 5 == 0:
            out.append("Buzz")
        else:
            out.append(str(i))
    return out


if __name__ == "__main__":
    print(greet("there"))
    print(" ".join(fizzbuzz(15)))
