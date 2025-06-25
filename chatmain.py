#!/usr/bin/env python

import sys
from dotenv import load_dotenv
load_dotenv()

from chatconf import set_config
import asyncio
from chatapi import api

def log_start(config):
    config.logger.info("Starting PEN Mailman server listening on {}://{}:{}/"
                       .format("https" if config.server_cert else "http",
                               config.server_address if config.server_address
                               else "*",
                               config.server_port))

if __name__ == "__main__":
    import os
    from uvicorn import Config, Server
    loop = asyncio.new_event_loop()
    config = set_config("chatserver", loop, sys.argv[1:])
    
    # For Render deployment
    config.server_address = "0.0.0.0"
    port = os.environ.get("PORT")
    if port:
        config.server_port = int(port)
    # Render's proxy handles SSL, so disable it in the app
    config.server_cert = None

    log_start(config)
    server = Server(Config(app=api(config),
                           host=config.server_address,
                           port=config.server_port,
                           ssl_certfile=config.server_cert
                               if config.server_cert else None,
                           loop=config.loop))
    config.loop.run_until_complete(server.serve())
else:
    loop = asyncio.get_event_loop()
    config = set_config(loop)
    log_start(config)
    app = api(config)
