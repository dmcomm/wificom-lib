'''
This file is part of the DMComm project by BladeSabre. License: MIT.
WiFiCom on Arduino Nano RP2040 Connect, with BladeSabre's pin assignments.
'''
import time
import board
# import busio
import digitalio
import usb_cdc

from dmcomm import CommandError, ReceiveError
import dmcomm.hardware as hw
import dmcomm.protocol
import dmcomm.protocol.auto
from wificom.hardware.rp2040_arduino_nano_connect import RP2040ArduinoNanoConnect, esp
from wificom.mqtt import platform_io

pins_extra_power = [
	(board.D6, False), (board.D7, True),
	(board.D8, False),
	(board.D11, False), (board.D12, True),
]
outputs_extra_power = []
for (pin, value) in pins_extra_power:
	output = digitalio.DigitalInOut(pin)
	output.direction = digitalio.Direction.OUTPUT
	output.value = value
	outputs_extra_power.append(output)

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

controller = hw.Controller()
controller.register(hw.ProngOutput(board.A0, board.A2))
controller.register(hw.ProngInput(board.A3))
controller.register(hw.InfraredOutput(board.D9))
controller.register(hw.InfraredInputModulated(board.D10))
controller.register(hw.InfraredInputRaw(board.D5))
controller.register(hw.TalisInputOutput(board.D4))

# Serial port selection
if usb_cdc.data is not None:
	serial = usb_cdc.data
else:
	serial = usb_cdc.console
#serial = usb_cdc.console  # same as REPL
#serial = usb_cdc.data  # alternate USB serial
#serial = busio.UART(board.TX, board.RX)  # for external UART

# Choose an initial digirom / auto-responder here:
digirom = None  # disable
#digirom = dmcomm.protocol.auto.AutoResponderVX("V")  # 2-prong auto-responder
#digirom = dmcomm.protocol.auto.AutoResponderVX("X")  # 3-prong auto-responder
#digirom = dmcomm.protocol.parse_command("IC2-0007-^0^207-0007-@400F" + "-0000" * 16)  # Twin any
# ...or use your own digirom, as for the Twin above.

rtb_went_first_time = None

serial.timeout = 1

def serial_print(contents):
	'''
	Print output to the serial console
	'''
	serial.write(contents.encode("utf-8"))

serial_print("dmcomm-python starting\n")

# Connect to WiFi
device = RP2040ArduinoNanoConnect()
device.connect_to_ssid()

# Connect to MQTT
platform_io_obj = platform_io.PlatformIO()
platform_io_obj.connect_to_mqtt(esp)

def execute_digirom(rom):
	error = ""
	result_end = "\n"
	try:
		controller.execute(rom)
	except (CommandError, ReceiveError) as e:
		error = repr(e)
		result_end = " "
	if not platform_io_obj.get_is_output_hidden():
		serial_print(str(rom.result) + result_end)
	else:
		serial_print("Received output, check the App\n")
	if error != "":
		serial_print(error + "\n")

def receive_rtb_legendz():
	rom_str = platform_io.rtb_digirom
	platform_io.rtb_digirom = None
	if not rom_str.startswith("LT1-"):
		serial_print("Expected Legendz\n")
		return None
	try:
		rom = dmcomm.protocol.parse_command(rom_str)
		execute_digirom(rom)
		return rom
	except CommandError as e:
		serial_print(repr(e) + "\n")
		return None

while True:
	time_start = time.monotonic()
	if serial.in_waiting != 0:
		digirom = None
		serial_bytes = serial.readline()
		serial_str = serial_bytes.decode("ascii", "ignore")
		# readline only accepts "\n" but we can receive "\r" after timeout
		if serial_str[-1] not in ["\r", "\n"]:
			serial_print("too slow\n")
			continue
		serial_str = serial_str.strip()
		serial_str = serial_str.strip("\0")
		serial_print(f"got {len(serial_str)} bytes: {serial_str} -> ")
		try:
			command = dmcomm.protocol.parse_command(serial_str)
			if hasattr(command, "op"):
				# It's an OtherCommand
				raise NotImplementedError("op=" + command.op)
			digirom = command
			serial_print(f"{digirom.physical}{digirom.turn}-[{len(digirom)} packets]\n")
		except (CommandError, NotImplementedError) as e:
			serial_print(repr(e) + "\n")
		time.sleep(1)
	replacementDigirom = platform_io_obj.get_subscribed_output()
	if replacementDigirom is not None:
		if not platform_io_obj.get_is_output_hidden():
			print("New digirom:", replacementDigirom)
		else:
			serial_print("Received digirom input, check the App\n")

	if replacementDigirom is not None:
		digirom = dmcomm.protocol.parse_command(replacementDigirom)

	if platform_io_obj.get_is_rtb_active():
		platform_io_obj.loop()
		if platform_io.rtb_battle_type == "legendz":
			if platform_io.rtb_user_type == "host":
				if rtb_went_first_time is None:
					rtb_rom = dmcomm.protocol.parse_command("LT0")
					execute_digirom(rtb_rom)
					if len(rtb_rom.result) == 2 and len(rtb_rom.result[0].data) >= 20:
						msg = "LT1-" + str(rtb_rom.result[0])[2:] + "-AA590003" * 3
						print(msg)
						platform_io_obj.on_rtb_digirom_output(msg)
						rtb_went_first_time = time.monotonic()
				elif time.monotonic() - rtb_went_first_time > 2:
					rtb_went_first_time = None
				elif platform_io.rtb_digirom is not None:
					rtb_went_first_time = None
					rtb_rom_executed = receive_rtb_legendz()
			elif platform_io.rtb_digirom is not None:
				rtb_rom_executed = receive_rtb_legendz()
				if len(rtb_rom_executed.result) >= 4:
					msg = "LT1-" + str(rtb_rom_executed.result[0])[2:] + "-AA590003" * 3
					print(msg)
					platform_io_obj.on_rtb_digirom_output(msg)
		else:
			serial_print(platform_io.rtb_battle_type + " not implemented\n")
	else:
		last_output = None
		if digirom is not None:
			execute_digirom(digirom)
			if len(str(digirom.result)) >= 1:
				last_output = str(digirom.result)

		# Send to MQTT topic (acts as a ping also)
		platform_io_obj.on_digirom_output(last_output)

		while (time.monotonic() - time_start) < 5:
			platform_io_obj.loop()
			if platform_io_obj.get_subscribed_output(False) is not None:
				break
			time.sleep(0.1)
