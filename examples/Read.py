#!/usr/bin/env python

import os
import signal
import time
import sys
import yaml
import logging
import logging.config
import coloredlogs

def setupLogging():
    path = './logging.yml'
    if os.path.exists(path):
        with open(path, 'rt') as f:
            try:
                config = yaml.safe_load(f.read())
                logging.config.dictConfig(config)
                coloredlogs.install()
            except Exception as e:
                print(e)
                print('Error in Logging Configuration. Using default configs')
                logging.basicConfig(level=logging.INFO)

setupLogging()

from pirc522 import RFID

logger = logging.getLogger(__name__)

run = True
rdr = RFID(pin_mode='BOARD', pin_rst=22, pin_irq=18)
util = rdr.util()
util.debug = True

def end_read(signal,frame):
    global run
    logger.info("Ctrl+C captured, ending read.")
    run = False
    rdr.cleanup()
    sys.exit()

signal.signal(signal.SIGINT, end_read)

logger.info("Starting")
while run:
    logger.info("Waiting...")
    time.sleep(0.1)
    rdr.wait_for_tag()

    (error, data) = rdr.request()
    if not error:
        logger.info("Detected: " + format(data, "02x"))

    (error, uid) = rdr.anticoll()
    if not error:
        logger.info("Card read UID: " + '_'.join("{:02X}".format(i) for i in uid))
        # print("Setting tag")
        # util.set_tag(uid)
        # print("Authorizing")
        # util.auth(rdr.auth_a, [0x12, 0x34, 0x56, 0x78, 0x96, 0x92])
        # util.auth(rdr.auth_b, [0x74, 0x00, 0x52, 0x35, 0x00, 0xFF])
        # print("Reading")
        # util.read_out(4)
        # print("Deauthorizing")
        # util.deauth()
