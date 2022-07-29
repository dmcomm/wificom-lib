'''
platform_io.py
Handle MQTT connections, subscriptions, and callbacks
'''
import json
from wificom.common.import_secrets import secrets_mqtt_broker, \
secrets_mqtt_username, \
secrets_mqtt_password, \
secrets_device_uuid, \
secrets_user_uuid
import adafruit_esp32spi.adafruit_esp32spi_socket as socket
import adafruit_minimqtt.adafruit_minimqtt as MQTT
from adafruit_io.adafruit_io import IO_MQTT
import dmcomm.protocol


 # Initialize a new MQTT Client object
mqtt_client = MQTT.MQTT(
	broker=secrets_mqtt_broker,
	port=1883,
	username=secrets_mqtt_username.lower(),
	password=secrets_mqtt_password
)

# Initialize an IO MQTT Client
io = IO_MQTT(mqtt_client)

last_application_id = None
is_output_hidden = None
new_digirom = None
rtb_user_type = None
rtb_active = False
rtb_host = None
battle_type = None
rtb_topic = None
class PlatformIO:
	'''
	Handles WiFi connection for Arduino Nano Connect board
	'''
	def __init__(self):
		self.mqtt_io_prefix = secrets_mqtt_username.lower() + "/f/"
		self.mqtt_topic_identifier = secrets_user_uuid + '-' + secrets_device_uuid
		self.mqtt_topic_input = self.mqtt_topic_identifier + '/wificom-input'
		self.mqtt_topic_output =  self.mqtt_io_prefix + self.mqtt_topic_identifier + "/wificom-output"

	def loop(self):
		'''
		Loop IO MQTT client
		'''
		io.loop()

	def get_subscribed_output(self, clear_rom=True):
		'''
		Get the output from the MQTT broker, and load in new Digirom (and clear if clear_rom is True)
		'''
		# pylint: disable=global-statement,global-variable-not-assigned
		global new_digirom
		returned_digirom = new_digirom

		if clear_rom:
			new_digirom = None

		return returned_digirom

	def get_is_output_hidden(self):
		'''
		Get the is_output_hidden value
		'''
		# pylint: disable=global-statement,global-variable-not-assigned
		global is_output_hidden

		return is_output_hidden

	def connect_to_mqtt(self, esp):
		'''
		Connect to the MQTT broker
		'''
		# Initialize MQTT interface with the esp interface
		MQTT.set_socket(socket, esp)

		# Connect the callback methods defined above to MQTT Broker
		io.on_connect = connected
		io.on_disconnect = disconnected
		io.on_subscribe =  subscribe
		io.on_unsubscribe = unsubscribe

		# Set up a callback for the led feed
		io.add_feed_callback(self.mqtt_topic_input, on_feed_callback)

		# Connect to MQTT Broker
		print("Connecting to MQTT Broker...")
		io.connect()

		# Subscribe to all messages on the mqtt_topic_input feed
		io.subscribe(self.mqtt_topic_input)

	def on_digirom_output(self, output):
		'''
		Send the output to the MQTT broker
		Set last_application_id for use serverside
		'''
		# 8 or less characters is the loaded digirom
		if output is not None and len(str(output)) > 8:
			# pylint: disable=global-statement,global-variable-not-assigned
			global last_application_id, rtb_active, rtb_user_type, rtb_topic
			# create json object containing output and device_uuid
			mqtt_message = {
				"application_uuid": last_application_id,
				"device_uuid": secrets_device_uuid,
				"output": str(output)
			}

			mqtt_message_json = json.dumps(mqtt_message)

			if rtb_active:
				mqtt_message["user_type"] = rtb_user_type
				mqtt_client.publish(self.mqtt_io_prefix + rtb_topic, mqtt_message_json)
			else:
				mqtt_client.publish(self.mqtt_topic_output, mqtt_message_json)



# Define callback functions which will be called when certain events happen.
def connected(client):
	# pylint: disable=unused-argument
	'''
	Connected function will be called when the client is connected to the MQTT Broker
	'''
	print("Connected to MQTT Broker! ")


def subscribe(client, userdata, topic, granted_qos):
	# pylint: disable=unused-argument
	'''
	This method is called when the client subscribes to a new feed.
	'''
	# pylint: disable=consider-using-f-string
	print("Subscribed to {0} with QOS level {1}".format(topic, granted_qos))

def unsubscribe(client, userdata, topic, granted_qos):
	# pylint: disable=unused-argument
	'''
	This method is called when the client unsubscribes to a feed.
	'''
	# pylint: disable=consider-using-f-string
	print("Unsubscribed to {0} with QOS level {1}".format(topic, granted_qos))


# pylint: disable=unused-argument
def disconnected(client):
	# pylint: disable=unused-argument
	'''
	Disconnected function will be called when the client disconnects.
	'''
	print("Disconnected from MQTT Broker!")


def on_feed_callback(client, topic, message):
	# pylint: disable=unused-argument
	'''
	Method called whenever user/feeds has a new value
	'''
	# pylint: disable=consider-using-f-string
	print("New message on topic {0}: {1} ".format(topic, message))
	# parse message as json
	message_json = json.loads(message)

	# pylint: disable=global-statement
	global last_application_id, is_output_hidden, new_digirom, rtb_user_type, \
		rtb_active, rtb_host, rtb_topic

	# if message_json contains topic_action
	if 'topic_action' in message_json:
		if  message_json['topic_action'] == "subscribe":
			rtb_topic = message_json['topic']
			rtb_active = True
			rtb_user_type = message_json['user_type']
			rtb_host = message_json['host']
			mqtt_client.subscribe(rtb_host + "/f/" + message_json['topic'])
			io.add_feed_callback(message_json['topic'], on_feed_callback)
		elif message_json['topic_action'] == "unsubscribe":
			print('unsubscribe received')
			rtb_active = False
			rtb_user_type = None
			last_application_id = message_json['application_id']
			is_output_hidden = message_json['hide_output']
			new_digirom = message_json['digirom']
			try:
				mqtt_client.unsubscribe(rtb_host + "/f/" + message_json['topic'])
			# pylint: disable=broad-except
			except (Exception) as error:
				print(error)
	else:
		if rtb_active:
			if 'user_type' in message_json:
				if message_json['user_type'] is not None and message_json['user_type'] != rtb_user_type:
					last_application_id = message_json['application_id']
					is_output_hidden = message_json['hide_output']
					# pylint: disable=broad-except
					try:
						# parse Digirom
						dmcomm.protocol.parse_command(message_json['output'])
						new_digirom = message_json['output']
					except (Exception) as error:
						print("Error parsing output, is it a Digirom?")
						print(error)
				else:
					print('rtb_user_type is not[' + rtb_user_type + '] ignoring Digirom')
		else:
			is_output_hidden = message_json['is_output_hidden']
			last_application_id = message_json['application_id']
			new_digirom = message_json['digirom']