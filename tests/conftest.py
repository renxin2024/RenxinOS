"""pytest 公共 fixture。"""

import pytest

import src.agent as agent


@pytest.fixture(autouse=True)
def reset_chunks_cache():
    """每个用例前清空 load_chunks 缓存，避免互相污染。"""
    agent._chunks_cache = None
    yield
    agent._chunks_cache = None
