from pydantic import RootModel


class Verdict(RootModel[bool]):
    def __bool__(self) -> bool:
        return self.root
