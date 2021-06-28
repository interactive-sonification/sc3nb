"""Classes for managing ID allocations."""

from abc import ABC, abstractmethod
from typing import Sequence


class Allocator(ABC):
    @abstractmethod
    def allocate(self, num: int = 1) -> Sequence[int]:
        raise NotImplementedError

    @abstractmethod
    def free(self, ids: Sequence[int]) -> None:
        raise NotImplementedError


class NodeAllocator(Allocator):
    """Allows allocating ids for Nodes."""

    def __init__(self, client_id: int) -> None:
        self.client_id = client_id
        self._num_node_ids = 0

    def allocate(self, num: int = 1) -> Sequence[int]:
        self._num_node_ids += 1
        if self._num_node_ids >= 2 ** 31:
            self._num_node_ids = 0
        return [self._num_node_ids + 10000 * (self.client_id + 1)]

    def free(self, ids: Sequence[int]) -> None:
        pass


class BlockAllocator(Allocator):
    """Allows allocating blocks of ids / indexes"""

    def __init__(self, num_ids: int, offset: int) -> None:
        self._offset = offset
        self._free_ids = [i + offset for i in range(num_ids)]

    def allocate(self, num: int = 1) -> Sequence[int]:
        """Allocate the next free ids

        Returns
        -------
        int
            free ids

        Raises
        ------
        RuntimeError
            When out of free ids or not enough ids are in order.
        """
        num_collected_ids = 1
        first_idx = 0
        idx = 0
        while num_collected_ids != num:
            if len(self._free_ids[first_idx:]) < num:
                raise RuntimeError(f"Cannot allocate {num} ids.")
            num_collected_ids = 1
            for idx in range(1, len(self._free_ids[first_idx:])):
                prev_id = self._free_ids[first_idx + idx - 1]
                next_id = self._free_ids[first_idx + idx]
                if abs(prev_id - next_id) > 1:
                    # difference between ids is too large
                    first_idx += idx
                    break
                num_collected_ids += 1
                if num_collected_ids == num:
                    break
        ids = self._free_ids[first_idx : first_idx + idx + 1]
        del self._free_ids[first_idx : first_idx + idx + 1]
        return ids

    def free(self, ids: Sequence[int]) -> None:
        """Mark ids as free again.

        Parameters
        ----------
        ids : sequence of int
            ids that are not used anymore.
        """
        for free_id in ids:
            self._free_ids.insert(free_id - self._offset, free_id)
