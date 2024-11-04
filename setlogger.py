import logging

LOG_FORMAT = "%(asctime)s.%(msecs)d %(lineno)d %(levelname)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

def set_logger(prog_name=None, log_file=None, logging_stdout=False,
               debug_mode=False):
    def get_logging_handler(channel):
        channel.setFormatter(logging.Formatter(fmt=LOG_FORMAT,
                                               datefmt=LOG_DATE_FORMAT))
        if debug_mode:
            channel.setLevel(logging.DEBUG)
        else:
            channel.setLevel(logging.INFO)
        return channel
    #
    # set logger.
    #   log_file: a file name for logging.
    logger = logging.getLogger(prog_name)
    if logging_stdout is True:
        logger.addHandler(get_logging_handler(logging.StreamHandler()))
    if log_file is not None:
        logger.addHandler(get_logging_handler(logging.FileHandler(log_file)))
    if debug_mode:
        logger.setLevel(logging.DEBUG)
        logger.debug("DEBUG mode")
    else:
        logger.setLevel(logging.INFO)
    return logger

