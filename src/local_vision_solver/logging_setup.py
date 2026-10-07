import logging
from logging.handlers import RotatingFileHandler
import time


def configure_logging(directory,name):
    directory.mkdir(parents=True,exist_ok=True)
    handler = RotatingFileHandler(directory/(name+'.log'),maxBytes=10*1024**2,backupCount=5,encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s UTC %(levelname)s %(name)s %(message)s')
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('uvicorn.access').disabled = True
