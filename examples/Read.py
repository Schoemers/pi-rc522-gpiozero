#!/usr/bin/env python

import signal
import time
import sys
import logging

from pirc522 import RFID

PIN_RST = 22  # e.g. 22

run = True
rdr = RFID(pin_mode='BOARD', pin_rst=PIN_RST, pin_irq=18)
util = rdr.util()
util.debug = True

logger = logging.getLogger(__name__)

def end_read(signal,frame):
    global run
    print("\nCtrl+C captured, ending read.")
    run = False
    rdr.cleanup()
    sys.exit()

signal.signal(signal.SIGINT, end_read)

print("Starting")
while run:
    print("Waiting...")
    time.sleep(0.1)
    rdr.wait_for_tag()

    (error, data) = rdr.request()
    if not error:
        print("Detected: " + format(data, "02x"))

    (error, uid) = rdr.anticoll()
    if not error:
        print("Card read UID: " + '_'.join("{:02X}".format(i) for i in uid))
        # print("Setting tag")
        # util.set_tag(uid)
        # print("Authorizing")
        # util.auth(rdr.auth_a, [0x12, 0x34, 0x56, 0x78, 0x96, 0x92])
        # util.auth(rdr.auth_b, [0x74, 0x00, 0x52, 0x35, 0x00, 0xFF])
        # print("Reading")
        # util.read_out(4)
        # print("Deauthorizing")
        # util.deauth()
