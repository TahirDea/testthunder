from aiohttp import web
from .stream_routes import routes


async def web_server():
    """
    Initializes the aiohttp web application with the necessary routes,
    custom middleware, and configures the maximum request body size.

    Returns:
        web.Application: The aiohttp web application instance.
    """
    # Create web application with custom middleware and set max client request size to 30 MB
    web_app = web.Application(middlewares=[custom_404_handler], client_max_size=30 * 1024 * 1024)
    web_app.add_routes(routes)
    return web_app
