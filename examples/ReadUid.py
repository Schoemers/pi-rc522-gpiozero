#!/usr/bin/env python
import logging
import pirc522
import RPi.GPIO as GPIO
import time

PIN_IRQ = 18  # e.g. 18
PIN_RST = 22  # e.g. 22
logger = logging.getLogger('ReadUid')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s  %(levelname).5s  %(message)s')

    logger.info(GPIO.RPI_INFO)

    try:
        reader = pirc522.RFID(pin_mode='BOARD', pin_rst=PIN_RST, pin_irq=PIN_IRQ)
        while True:
            reader.wait_for_tag()
            uid = reader.read_id(True)
            if uid is not None:
                logger.info(f'UID: {uid:X}')
            else:
                logger.error('no UID')
            time.sleep(1)

    except KeyboardInterrupt:
        pass

    finally:
        reader.cleanup()
