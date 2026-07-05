import logging
import threading
import time
import spidev
import gpiozero

RASPBERRY = object()
BEAGLEBONE = object()
board = RASPBERRY
PIN_MODES_BOARD = ['BOARD', 'BOARD_DEFAULT']
PIN_MODES_BCM = ['BCM']
try:
    import RPi.GPIO as GPIO  # only for pin mode selection compatibility

    PIN_MODES_BOARD.append(GPIO.BOARD)
    PIN_MODES_BCM.append(GPIO.BCM)
except ImportError:
    pass

SPIClass = spidev.SpiDev
def_pin_rst = 22
def_pin_irq = 18
def_pin_mode = 'BOARD_DEFAULT'


def timed_out(start_time, timeout) -> bool:
    return timeout != 0 and (time.time() - start_time) >= timeout


def crc_check(back_data):
    if len(back_data) != 5:
        return False

    crc_sum = 0
    for value in back_data[:4]:
        crc_sum = crc_sum ^ value

    if crc_sum != back_data[4]:
        return False

    return True


class RFID(object):
    pin_rst = 22
    pin_ce = 0
    pin_irq = 18

    addr_CommandReg = 0x01
    addr_ComIEnReg = 0x02
    addr_DivIEnReg = 0x03
    addr_ComIrqReg = 0x04
    addr_DivIrqReg = 0x05
    addr_ErrorReg = 0x06
    addr_Status1Reg = 0x07
    addr_Status2Reg = 0x08
    addr_FIFODataReg = 0x09
    addr_FIFOLevelReg = 0x0A
    addr_ControlReg = 0x0C
    addr_BitFramingReg = 0x0D
    addr_ModeReg = 0x11
    addr_TxControlReg = 0x14
    addr_TxASKReg = 0x15
    addr_RFCfgReg = 0x26
    addr_TModeReg = 0x2A
    addr_TPrescalerReg = 0x2B
    addr_TReloadRegHI = 0x2C
    addr_TReloadRegLO = 0x2D
    addr_CRCResultRegMSB = 0x21
    addr_CRCResultRegLSB = 0x22

    logger = None

    addr_names = {
        0x01: "CommandReg      ",
        0x02: "ComIEnReg       ",
        0x03: "DivIEnReg       ",
        0x04: "ComIrqReg       ",
        0x05: "DivIrqReg       ",
        0x06: "ErrorReg        ",
        0x07: "Status1Reg      ",
        0x08: "Status2Reg      ",
        0x09: "FIFODataReg     ",
        0x0A: "FIFOLevelReg    ",
        0x0C: "ControlReg      ",
        0x0D: "BitFramingReg   ",
        0x11: "ModeReg         ",
        0x14: "TxControlReg    ",
        0x15: "TxASKReg        ",
        0x26: "RFCfgReg        ",
        0x2A: "TModeReg        ",
        0x2B: "TPrescalerReg   ",
        0x2C: "TReloadRegHI    ",
        0x2D: "TReloadRegLO    ",
        0x21: "CRCResultRegMSB ",
        0x22: "CRCResultRegLSB ",
    }

    bit_Tx1RFEn = 1 << 0
    bit_Tx2RFEn = 1 << 1

    mode_idle = 0x00
    mode_auth = 0x0E
    mode_receive = 0x08
    mode_transmit = 0x04
    mode_transrec = 0x0C
    mode_reset = 0x0F
    mode_crc = 0x03

    auth_a = 0x60
    auth_b = 0x61

    act_read = 0x30
    act_write = 0xA0
    act_increment = 0xC1
    act_decrement = 0xC0
    act_restore = 0xC2
    act_transfer = 0xB0

    act_reqidl = 0x26
    act_reqall = 0x52
    act_anticl = 0x93
    act_anticl2 = 0x95
    act_anticl3 = 0x97
    act_select = 0x93
    act_end = 0x50

    length = 16

    antenna_gain = 0x04

    # antenna_gain
    #  defines the receiver's signal voltage gain factor:
    #  000 18 dB HEX = 0x00
    #  001 23 dB HEX = 0x01
    #  010 18 dB HEX = 0x02
    #  011 23 dB HEX = 0x03
    #  100 33 dB HEX = 0x04
    #  101 38 dB HEX = 0x05
    #  110 43 dB HEX = 0x06
    #  111 48 dB HEX = 0x07
    # 3 to 0 reserved - reserved for future use

    authed = False
    irq = threading.Event()

    def __init__(
            self,
            bus=0,
            device=0,
            speed=1000000,
            pin_rst=None,
            pin_ce=0,
            pin_irq=None,
            pin_mode=def_pin_mode,
            antenna_gain=None
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.warning(f'RFID-init pin_irq: {pin_irq}, pin_rst: {pin_rst}, pin_mode: {pin_mode}')
        if not pin_rst:
            # As this code may now run on non-Raspberry devices, ask for
            # explicit PIN definitions to avoid hardware damage.
            raise RuntimeError('no RST GPIO defined, please pass pin_rst= '
                               '(previous default: {def_pin_rst})')
        if not pin_irq:
            self.logger.info('No IRQ GPIO defined (previous default: '
                        '{def_pin_irq}), wait_for_tag() not supported')

        self.pin_rst = pin_rst
        self.pin_ce = pin_ce
        self.pin_irq = pin_irq

        self.spi = SPIClass()
        self.spi.open(bus, device)
        if board == RASPBERRY:
            self.spi.max_speed_hz = speed
        else:
            self.spi.mode = 0
            self.spi.msh = speed

        if pin_mode:
            if pin_mode in PIN_MODES_BOARD:
                self.pin = lambda p: f'BOARD{p}'
            elif pin_mode in PIN_MODES_BCM:
                self.pin = lambda p: f'BCM{p}'
            else:
                raise RuntimeError("unsupported pin mode")

        if self.pin_rst is not None:
            reset_pin = self.pin(pin_rst)
            self.logger.debug(f'register reset on {reset_pin}')
            self.output_rst = gpiozero.OutputDevice(reset_pin)
            self.output_rst.on()

        # Ignore IRQ if we did not wire this
        if self.pin_irq is not None:
            irq_pin = self.pin(pin_irq)
            self.logger.debug(f'register irq_callback on {irq_pin}')
            self.input_irq = gpiozero.DigitalInputDevice(irq_pin, pull_up=True)
            self.input_irq.when_deactivated = self.irq_callback

        # Change the antenna gain
        if antenna_gain is not None:
            self.antenna_gain = antenna_gain

        if pin_ce != 0:
            self.output_ce = gpiozero.OutputDevice(self.pin(pin_ce))
            self.output_ce.on()
        self.init()

    def disable_interrupts(self):
        self.logger.debug('disable_interrupts')
        self.dev_write(self.addr_ComIEnReg, 0x80)
        self.dev_write(self.addr_DivIEnReg, 0x00)
        self.dev_write(self.addr_ComIrqReg, 0x14)
        self.dev_write(self.addr_DivIrqReg, 0x00)

    def init(self):
        self.logger.debug('init')
        self.reset()
        self.disable_interrupts()
        self.dev_write(self.addr_TxASKReg, 0x40)
        self.dev_write(self.addr_ModeReg, 0x3D)
        self.set_antenna_gain(self.antenna_gain)
        self.set_antenna(True)

    def spi_transfer(self, data):
        if self.pin_ce != 0:
            self.output_ce.off()
        r = self.spi.xfer2(data)
        if self.pin_ce != 0:
            self.output_ce.on()
        return r

    def dev_write(self, address, value):
        self.logger.debug(f'write       {self.addr_names[address]}: {value:02x}')
        l_address = (address << 1) & 0x7E
        self.spi_transfer([l_address, value])

    def dev_read(self, address):
        l_address = ((address << 1) & 0x7E) | 0x80
        value = self.spi_transfer([l_address, 0])[1]
        self.logger.debug(f'read        {self.addr_names[address]}: {value:02x}')
        return value

    def set_bitmask(self, address, mask):
        self.logger.debug(f'set bitmask {self.addr_names[address]}: {mask:02x}')
        current = self.dev_read(address)
        self.dev_write(address, current | mask)

    def clear_bitmask(self, address, mask):
        self.logger.debug(f'cls bitmask {self.addr_names[address]}: {mask:02x}')
        current = self.dev_read(address)
        self.dev_write(address, current & (~mask))

    def set_antenna(self, state):
        self.logger.debug('set_antenna')
        val = self.bit_Tx1RFEn | self.bit_Tx2RFEn
        if state:
            current = self.dev_read(self.addr_TxControlReg)
            if ~(current & val):
                self.set_bitmask(self.addr_TxControlReg, val)
        else:
            self.clear_bitmask(self.addr_TxControlReg, val)

    def set_antenna_gain(self, gain):
        """
        Sets antenna gain from a value from 0 to 7.
        """
        self.logger.debug('set_antenna_gain')
        if 0 <= gain <= 7:
            self.antenna_gain = gain
            self.dev_write(self.addr_RFCfgReg, (self.antenna_gain << 4))
        else:
            raise ValueError('Antenna gain has to be in the range 0...7')

    def card_write(self, command, data):
        back_data = []
        back_length = 0
        error = False
        irq = 0x00
        irq_wait = 0x00

        if command == self.mode_auth:
            irq = 0x12
            irq_wait = 0x10
        if command == self.mode_transrec:
            irq = 0x77
            irq_wait = 0x30

        self.dev_write(self.addr_ComIEnReg, irq | 0x80)
        self.clear_bitmask(self.addr_ComIrqReg, 0x80)
        self.set_bitmask(self.addr_FIFOLevelReg, 0x80)
        self.dev_write(self.addr_CommandReg, self.mode_idle)

        for value in data:
            self.dev_write(self.addr_FIFODataReg, value)

        self.dev_write(self.addr_CommandReg, command)

        if command == self.mode_transrec:
            self.set_bitmask(self.addr_BitFramingReg, 0x80)

        i = 2000
        while True:
            n = self.dev_read(self.addr_ComIrqReg)
            i -= 1
            if ~((i != 0) and ~(n & 0x01) and ~(n & irq_wait)):
                break

        self.clear_bitmask(self.addr_BitFramingReg, 0x80)

        if i != 0:
            if (self.dev_read(self.addr_ErrorReg) & 0x1B) == 0x00:
                error = False

                if n & irq & 0x01:
                    self.logger.warning("Error E1")
                    error = True

                if command == self.mode_transrec:
                    n = self.dev_read(self.addr_FIFOLevelReg)
                    last_bits = self.dev_read(self.addr_ControlReg) & 0x07
                    if last_bits != 0:
                        back_length = (n - 1) * 8 + last_bits
                    else:
                        back_length = n * 8

                    if n == 0:
                        n = 1

                    if n > self.length:
                        n = self.length

                    for _i in range(n):
                        back_data.append(self.dev_read(self.addr_FIFODataReg))
            else:
                self.logger.warning("Error E2")
                error = True

        return error, back_data, back_length

    def read_id(self, as_number=False):
        """
        Obtains the id (4 or 7 bytes) of a tag (if present)
        Return None on error or not present, otherwise returns tag ID

        The as_number argument can be used to return the UID as an integer. It
        defaults to a list like the rest of the API.
        """

        # Check if there is anything there
        error, tag_type = self.request()
        if error:
            return None

        # Get the UID
        error, uid = self.anticoll()
        if error:
            return None

        # Do we have an incomplete UID?!
        if uid[0] != 0x88:
            return int.from_bytes(uid[0:4], 'big') if as_number else uid[0:4]

        # Activate the tag with the incomplete UID
        error = self.select_tag(uid)
        if error:
            return None

        # Get the remaining bytes
        error, uid2 = self.anticoll2()
        if error:
            return None

        self.disable_interrupts()

        # Build the final UID without checksums
        real_uid = uid[1:-1] + uid2[:-1]
        return int.from_bytes(real_uid, 'big') if as_number else real_uid

    def request(self, req_mode=0x26):
        """
        Requests for tag.
        Returns (False, None) if no tag is present, otherwise returns (True, tag type)
        """

        self.dev_write(self.addr_BitFramingReg, 0x07)
        (error, back_data, back_bits) = self.card_write(self.mode_transrec, [req_mode, ])

        if error or (back_bits != 0x10):
            return True, None

        return False, back_bits

    def __anticoll_internal(self, type):

        self.dev_write(self.addr_BitFramingReg, 0x00)
        (error, back_data, back_bits) = self.card_write(self.mode_transrec, [type, 0x20])

        if not error:
            if not crc_check(back_data):
                error = True

        return error, back_data

    def anticoll(self):
        """
        Anti-collision detection.
        Returns tuple of (error state, tag ID).
        """

        return self.__anticoll_internal(self.act_anticl)

    def anticoll2(self):
        """
        Anti-collision detection.
        Returns tuple of (error state, tag ID).
        """

        return self.__anticoll_internal(self.act_anticl2)

    def calculate_crc(self, data):
        self.clear_bitmask(self.addr_DivIrqReg, 0x04)
        self.set_bitmask(self.addr_FIFOLevelReg, 0x80)

        for value in data:
            self.dev_write(self.addr_FIFODataReg, value)
        self.dev_write(self.addr_CommandReg, self.mode_crc)

        i = 255
        while True:
            n = self.dev_read(self.addr_DivIrqReg)
            i -= 1
            if i == 0 or (n & 0x04):
                break
            time.sleep(0.25)

        return [self.dev_read(self.addr_CRCResultRegLSB), self.dev_read(self.addr_CRCResultRegMSB)]

    def select_tag(self, uid):
        """
        Selects tag for further usage.
        uid -- list or tuple with four bytes tag ID
        Returns error state.
        """

        buffer = [self.act_select, 0x70]
        buffer.extend(uid[:5])
        buffer.extend(self.calculate_crc(buffer))
        (error, back_data, back_length) = self.card_write(self.mode_transrec, buffer)

        if (not error) and (back_length == 0x18):
            return False
        else:
            return True

    def card_auth(self, auth_mode, block_address, key, uid):
        """
        Authenticates to use specified block address. Tag must be selected using select_tag(uid) before auth.
        auth_mode -- RFID.auth_a or RFID.auth_b
        key -- list or tuple with six bytes key
        uid -- list or tuple with four bytes tag ID
        Returns error state.
        """

        buffer = [auth_mode, block_address]
        buffer.extend(key)
        buffer.extend(uid[:4])

        (error, back_data, back_length) = self.card_write(self.mode_auth, buffer)
        if not (self.dev_read(self.addr_Status2Reg) & 0x08) != 0:
            error = True

        if not error:
            self.authed = True

        return error

    def stop_crypto(self):
        """Ends operations with Crypto1 usage."""
        self.clear_bitmask(self.addr_Status2Reg, 0x08)
        self.authed = False

    def halt(self):
        """Switch state to HALT"""

        buffer = [self.act_end, 0]

        self.clear_bitmask(self.addr_Status2Reg, 0x80)
        self.card_write(self.mode_transrec, buffer)
        self.clear_bitmask(self.addr_Status2Reg, 0x08)
        self.authed = False

    def read(self, block_address):
        """
        Reads data from block. You should be authenticated before calling read.
        Returns tuple of (error state, read data).
        """
        buffer = [self.act_read, block_address]
        buffer.extend(self.calculate_crc(buffer))
        (error, back_data, back_length) = self.card_write(self.mode_transrec, buffer)

        if len(back_data) != 16:
            error = True

        return error, back_data

    def write(self, block_address, data):
        """
        Writes data to block. You should be authenticated before calling write.
        Returns error state.
        """
        buffer = [self.act_write, block_address]
        buffer.extend(self.calculate_crc(buffer))
        (error, back_data, back_length) = self.card_write(self.mode_transrec, buffer)
        if not (back_length == 4) or not ((back_data[0] & 0x0F) == 0x0A):
            error = True

        if not error:
            buffer = []
            buffer.extend(data[:16])
            buffer.extend(self.calculate_crc(buffer))
            (error, back_data, back_length) = self.card_write(self.mode_transrec, buffer)
            if not (back_length == 4) or not ((back_data[0] & 0x0F) == 0x0A):
                error = True

        return error

    def irq_callback(self):
        self.logger.debug("irq_callback")
        self.irq.set()

    def wait_for_tag(self, timeout=0):
        if self.pin_irq is None:
            raise NotImplementedError('Waiting not implemented if IRQ is not used')
        self.logger.debug(f'wait_for_tag(timeout={timeout})')
        # enable IRQ on detect
        self.init()
        self.irq.clear()
        self.dev_write(self.addr_ComIrqReg, 0x00)
        self.dev_write(self.addr_ComIEnReg, 0xA0)
        # wait for it
        start_time = time.time()
        waiting = True
        while waiting and not timed_out(start_time, timeout):
            self.init()
            self.dev_write(self.addr_ComIrqReg, 0x00)
            self.dev_write(self.addr_ComIEnReg, 0xA0)

            # Even when using the interrupt line this is needed
            # to force the controller to re-scan regularly:
            self.dev_write(self.addr_FIFODataReg, 0x26)
            self.dev_write(self.addr_CommandReg, 0x0C)
            self.dev_write(self.addr_BitFramingReg, 0x87)
            waiting = not self.irq.wait(0.2)
        self.irq.clear()

    def reset(self):
        self.logger.debug('reset')
        self.dev_write(self.addr_CommandReg, self.mode_reset)
        self.authed = False

    def cleanup(self):
        """
        Calls stop_crypto() if needed
        """
        if self.authed:
            self.stop_crypto()

    def util(self):
        """
        Creates and returns RFIDUtil object for this RFID instance.
        If module is not present, returns None.
        """
        try:
            from .util import RFIDUtil
            return RFIDUtil(self)
        except ImportError:
            return None
