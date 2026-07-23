import pytest
import asyncio
from app.browser import BrowserPool

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_browser_pool_lifecycle():
    pool = BrowserPool()
    await pool.start()
    assert pool._browser is not None
    assert pool._browser.is_connected()
    
    # Test context creation
    async with pool.new_context() as context:
        page = await context.new_page()
        assert page is not None
        await page.close()
        
    await pool.stop()
    assert pool._browser is None
    assert pool._playwright is None

@pytest.mark.anyio
async def test_browser_pool_recovery_on_close():
    pool = BrowserPool()
    await pool.start()
    
    # Simulate sudden process/transport kill
    if pool._browser:
        await pool._browser.close()
    
    # Pool should detect disconnected state and recover automatically on next context
    async with pool.new_context() as context:
        page = await context.new_page()
        assert page is not None
        await page.close()
        
    await pool.stop()
