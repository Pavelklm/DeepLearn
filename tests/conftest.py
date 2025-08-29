"""
Конфигурация для pytest
"""
import pytest
import asyncio

# Настройка asyncio для pytest
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Автоматически применять asyncio marker ко всем async функциям
def pytest_collection_modifyitems(config, items):
    for item in items:
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)
