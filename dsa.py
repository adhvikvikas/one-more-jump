"""Data Structures & Algorithms module: Bounded Stack implementation.

Provides a fixed-capacity LIFO (Last-In, First-Out) stack used for checkpoint
tracking and "Second Chance" rewinds in One More Jump.

Time Complexity:
- push(item): O(1) amortized when not full. When full, discarding the oldest
  item from index 0 of an internal list is O(n); with a small fixed capacity
  (capacity=3), n <= 3 so this operation is negligible and effectively O(1).
- pop(): O(1)
- peek(): O(1)
- is_empty(), is_full(), size(): O(1)
"""

from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


class Stack(Generic[T]):
    """A bounded LIFO stack that drops the oldest item on overflow."""

    def __init__(self, capacity: int = 3) -> None:
        if capacity <= 0:
            raise ValueError("Capacity must be greater than zero.")
        self.capacity: int = capacity
        self._items: List[T] = []

    def push(self, item: T) -> None:
        """Push an item onto the stack.

        If the stack has reached capacity, the oldest item (at index 0, bottom
        of the stack) is discarded before adding the new item at the top.
        """
        if len(self._items) >= self.capacity:
            self._items.pop(0)  # Evict oldest entry on overflow
        self._items.append(item)

    def pop(self) -> Optional[T]:
        """Remove and return the top item from the stack (LIFO).

        Returns None if the stack is empty.
        """
        if self.is_empty():
            return None
        return self._items.pop()

    def peek(self) -> Optional[T]:
        """Return the top item without removing it.

        Returns None if the stack is empty.
        """
        if self.is_empty():
            return None
        return self._items[-1]

    def is_empty(self) -> bool:
        """Check whether the stack contains no items."""
        return len(self._items) == 0

    def is_full(self) -> bool:
        """Check whether the stack is currently at capacity."""
        return len(self._items) >= self.capacity

    def size(self) -> int:
        """Return the current number of items on the stack."""
        return len(self._items)

    def __len__(self) -> int:
        return self.size()

    def clear(self) -> None:
        """Remove all items from the stack."""
        self._items.clear()

    def to_list(self) -> List[T]:
        """Return a shallow copy of items from bottom to top for inspection."""
        return list(self._items)
