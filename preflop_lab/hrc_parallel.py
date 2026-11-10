"""Validate the optional data-only worker RNG trailer on native v3 checkpoints."""
import struct


def validate_trailer(data, primary_rng, *, expected_threads=None):
    if not data:
        count=1
    else:
        if len(data)<12 or data[:8]!=b'HRPAR001':
            raise ValueError('未知并行检查点尾部。')
        count=struct.unpack_from('<I',data,8)[0]
        if not 2<=count<=32 or len(data)!=12+32*count:
            raise ValueError('并行随机流数量或长度无效。')
        states=[struct.unpack_from('<4Q',data,12+32*i) for i in range(count)]
        if any(not any(state) for state in states) or len(set(states))!=count:
            raise ValueError('并行随机流无效或重复。')
        if states[0]!=tuple(primary_rng):
            raise ValueError('并行主随机流与检查点不一致。')
    if expected_threads is not None and (type(expected_threads) is not int or expected_threads!=count):
        raise ValueError('并行线程数与检查点索引不一致。')
    return count
