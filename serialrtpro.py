# Save on Pico as "main.py" for autoboot
import serial.tools.list_ports
import serial
import time
from datetime import datetime

import re
import string

def replace_non_printable(input_string):
    # Define a regular expression to match non-printable characters
    return re.sub(r'[^' + re.escape(string.printable) + r']', '?', input_string)

def parse_microgate_standard_and_extended(data, request_annul_double_starts):
    global last_time_of_day_logical_was_start

    # remember python slices are exclusive of upper bound number
    if data[0] == '\x10':
        print(datetime.now().strftime("%H:%M:%S "), end='')

        # byte 0 was protocol type \x10
        stopwatch_id = data[1]
        device_addr = data[2]
        dummychar1 = data[3]

        program_in_use = data[4]
        print("protocol(" + ("Std" if message_type_standard else "Ext" if message_type_extended else "???") + ")",
              f"program({program_in_use})",
              #sep='',
              end='')

        mode = data[5]              # O=Online, F=Offline
        mode_online = mode == "O"
        mode_offline = mode == "F"
        if not mode_online:
            print(" mode(" + ("online" if mode_online else "offline" if mode_offline else "???") + ")",
                  end='')
            return  # no further processing on this message (although offline would work as well)

        progressive_message_count = data[6:12]

        competitor = data[12:17]
        try:
            print(f" comp({int(competitor)})",
                  end='')
        except ValueError:
            print(f" comp({competitor})")


        group_or_category = data[17:20]

        run = data[20:23]
        try:
            print(f" run({int(run)})",
                  end='')
        except ValueError:
            print(f" run({run})")

        physical_channel = data[23:26]

        # extended protocol inserts two bytes to logical channel, and changes STOP value
        logical_channel = (data[26:29], data[26:31]) [message_type_extended]
        logical_channel_is_start = logical_channel == "000" or logical_channel == "00000"
        logical_channel_is_stop = logical_channel == "255" or logical_channel == "65535"

        # full list of info type codes is in protocol document, not all are listed here
        info = (data[29], data[31]) [message_type_extended]
        info_is_time_of_day = info == '0'
        info_is_run_time = info == '1'
        info_is_total_time = info == '2'
        info_is_lap_time = info == '3'
        info_is_speed = info == '4'
        info_is_annul = info == 'a'
        info_is_dnf = info == 'A'
        info_is_dsq = info == 'Q'
        info_is_not_started = info = 'P'
        info_is_skipped_unassigned = info == 'S'
        info_is_skipped_assigned = info == 's'
        info_is_manual_mod_time = info == 'K'
        info_is_time_substitute = info == 'C'
        info_is_time_net_basic = info == 'Z'

        time_or_speed = (data[30:40], data[32:42]) [message_type_extended]

        # if time of day, then date
        # otherwise, + or - char, followed by net number of days (usually seven zeros!)
        date_or_net_days = (data[40:48], data[42:50]) [message_type_extended]

        dummchars2 = (data[48:50], data[50:52]) [message_type_extended]

        # eol removed from data already (available in full_line)
        #carriage_return (index 50 or 52)
        #line_feed (index 51 or 53)
        # (remember index is 0 based, so 52 char message is indexed 0:51)

        if mode_online:
            show_time_and_date = info_is_time_of_day or info_is_run_time or info_is_total_time or info_is_lap_time or info_is_annul

            print(" logical_ch("
                  + ("START" if logical_channel_is_start
                        else "STOP" if logical_channel_is_stop
                        else logical_channel)
                  + ")",
                  end='')

            print(" info("
                  + ("Time of day" if info_is_time_of_day
                        else "Run time" if info_is_run_time
                        else "Total time" if info_is_total_time
                        else "Lap time" if info_is_lap_time
                        else "Annulled" if info_is_annul
                        else "DNF" if info_is_dnf
                        else "(info type not decoded")
                  + ")",
                  end='')

            if show_time_and_date:
                print(f" time({reformat_time_with_punctuation(time_or_speed)})",
                        end=''
                      )
                if info_is_run_time or info_is_total_time or info_is_lap_time or info_is_time_net_basic:
                    print(f" days({reformat_delta_date(date_or_net_days)})",
                          end='')
                elif info_is_speed:
                    print(f" speed({date_or_net_days})",
                           end='')
                else:   # date from a time-of-day
                    print(f" date({reformat_ddmmyyyy_to_mm_dd_yyyy(date_or_net_days)})",
                            end='')

            print('')   # end of line

            # since online, update logical filters
            if info_is_time_of_day:
                if logical_channel_is_start:
                    if last_time_of_day_logical_was_start:
                        print("2+ STARTS SINCE FINISH")
                        if request_annul_double_starts:
                            ask_annul_data = "\x17R a"  # request annul
                            ask_annul_data += competitor + logical_channel # not yet resolved: known RTPro bug as of Dec2024: logical_channel response, at least stop, needs to be 3 bytes even for extended protocol (which sends 5 bytes)
                            ask_annul_data += "900" # PC edited event
                            ask_annul_data += run
                            ask_annul_data += time_or_speed # overwrite event detected
                            ask_annul_data += date_or_net_days
                            ask_annul_data += '\x0d'
                            send_request(ask_annul_data)

                    else:
                        print("ATHLETE START")
                    last_time_of_day_logical_was_start = True

                elif logical_channel_is_stop:
                    if last_time_of_day_logical_was_start:
                        print("ATHLETE STOP")
                    else:
                        print("2+ STOPS SINCE START")
                    last_time_of_day_logical_was_start = False
            elif info_is_dnf:
                if last_time_of_day_logical_was_start:
                    print("ATHLETE DNF")
                else:
                    print("ODD DNF AFTER MISSING START")
                last_time_of_day_logical_was_start = False


        elif mode_offline:
            print("Offline mode message")

        else:
            print("Unknown mode in message")
    else:
        print("Message not standard or extended protocol")



def parse_reduced(data):
    if data[0] == '\x14':
        print(datetime.now().strftime("%H:%M:%S "), end='')

        # byte 0 was protocol type \x14
        device_addr = data[1]

        id_device_requesting = data[2]
        print(f"protocol(Red), request_device({id_device_requesting})",
              end='')

        competitor = data[3:8]
        try:
            print(f" comp({int(competitor)})",
                  end='')
        except ValueError:
            print(f" comp({competitor})")

        # protocol document has full list of code values, not all listed here
        info = data[8]
        info_is_run_running_split = info == 'A'
        info_is_total_running_split = info == 'B'
        info_is_lap_running = info == 'C'
        info_is_dynamic_running = info == 'D'
        info_is_run_net_split = info == 'a'
        info_is_total_net_split = info == 'b'
        info_is_lap_net = 'c'
        info_is_dynamic_net = 'd'
        print(" info("
              + ("run_running" if info_is_run_running_split
                 else "total running" if info_is_total_running_split
                 else "lap running" if info_is_lap_running
                 else "dynamic running" if info_is_dynamic_running
                 else "run net" if info_is_run_net_split
                 else "total net" if info_is_total_net_split
                 else "lap net" if info_is_lap_net
                 else "dynamic net" if info_is_dynamic_net
                 else "???")
              + ")",
              end='')

        time = data[9:19]
        print(f" time({reformat_time_with_punctuation(time)})",
              end='')

        # '-' is negative; 0-9 is number of days; + means more than 9; other codes in protocol document
        num_days = data[19]
        print(f" days({num_days[0]})",
              end='')

        run = data[20:23]
        try:
            print(f" run({int(run)})",
                  end='')
        except ValueError:
            print(f" run({run})")

        lap = data[23:26]
        try:
            print(f" lap({int(lap)})",
                  end='')
        except ValueError:
            print(f" lap({lap})")

        # three digits
        # or 000 if calculation of ranking is disabled
        # or --- if being recalculated
        # or +++ if greater than 999
        position = data[26:29]
        try:
            print(f" pos({int(position)})",
                  end='')
        except ValueError:
            print(f" pos({position})")


        dummychars = data[29:30]
        # then carriage return \x0D
        # then line feed \x0A
        print('')   # end of line

    else:
        print("Message not reduced protocol")


def send_request(ask_data):
    #if len(ask_data) == 37 and ask_data[0] == '\x17':
    try:
        ser.write(ask_data.encode('utf-8'))
        print("Sent request to timer")

    except Exception as local_exception:
        print(f"Error at write: {local_exception}")


def reformat_ddmmyyyy_to_mm_dd_yyyy(my_date):
    month_names = ("Jan","Feb","Mar",
                  "Apr","May","Jun",
                  "Jul","Aug","Sep",
                  "Oct","Nov","Dec")
    try:
        return month_names[int(my_date[2:4])-1] + "/" + my_date[0:2] + "/" + my_date[4:8]

    except (ValueError, OverflowError, IndexError):
        return f"??{my_date}??"

def reformat_delta_date(my_delta_date):
    plus_minus = my_delta_date[0]
    try:
        num_delta_days = int(my_delta_date[1:8])
        return plus_minus + f"{num_delta_days}"
    except ValueError:
        return my_delta_date


def reformat_time_with_punctuation(my_time):
    try:
        return my_time[0:2] + ":" + my_time[2:4] + ":" + my_time[4:6] + "." + my_time[7:11]

    except IndexError:
        return f"??{my_time}??"

##################################################### main code
while True:
    # Get a list of all serial ports
    ports = serial.tools.list_ports.comports()

    # Check if there are any serial ports available
    if ports:
        print("Available serial ports:")
        for index, port in enumerate(ports, start=0):
            print(f"{index}: {port.device} - {port.description}")

        # port_select = input("Enter port choice: ")
        #
        # try:
        #     # Try to convert the input to an integer
        #     port_select_number = int(port_select)
        #     if port_select_number < 0 or port_select_number >= len(ports):
        #         print("Not a listed choice")
        #         exit()
        #     port_name = ports[port_select_number].device
        #     print(f"Opening {port_select_number}: {port_name}")
        # except ValueError:
        #     print("That's not a valid integer!")
        #     exit()

        port_name = ""
        for port in ports:
            if port.device not in ("COM1"):   # this is not the ports you are looking for... anymore
                port_name = port.device
                break
        if port_name != "":
            print(f"Selected {port_name}")

            # Specify the serial port and baud rate
            baud_rate = 19200  # Baud rate (change to match your device's settings)

            ser = None
            try:
                # Open the serial port
                ser = serial.Serial(port_name, baud_rate, timeout=1)

                # Ensure the serial port is opened correctly
                if ser.is_open:
                    print(datetime.now().strftime("%H:%M:%S "), end='')
                    print(f"Connected to {port_name} at speed {baud_rate}")

                    # for single-athlete filtering, begin by expecting Start events
                    last_time_of_day_logical_was_start = False
                    do_request_annuls_of_double_starts = True

                    # Read data continuously from the serial port
                    while True:
                        if ser.in_waiting > 0:
                            # Read one line from the serial port
                            full_line = ser.readline()
                            data = full_line.decode('utf-8').rstrip("\r\n")    # decode bytes to string and strip closing newline
                            output_string = replace_non_printable(data)
                            #print(repr(output_string))  # Shows the result

                            full_line_length = len(full_line)

                            protocol_char = data[0]
                            message_type_standard = False
                            message_type_extended = False
                            message_type_reduced = False
                            show_line_data = False
                            if full_line_length == 52 and protocol_char == '\x10':
                                # microgate standard protocol non-tick information message
                                message_type_standard = True
                                parse_microgate_standard_and_extended(data, do_request_annuls_of_double_starts)

                            elif full_line_length == 54 and protocol_char == '\x10':
                                # microgate extended protocol non-tick information message
                                message_type_extended = True
                                parse_microgate_standard_and_extended(data, do_request_annuls_of_double_starts)

                            elif full_line_length == 33 and protocol_char == '\x14':
                                # reduced protocol message
                                message_type_reduced = True
                                parse_reduced(data)

                            elif full_line_length == 52 and protocol_char == '\x12':
                                print(datetime.now().strftime("%H:%M:%S "), end='')
                                print("Static reply message (not parsed)")

                            elif full_line_length == 10 and protocol_char == '\x17':
                                print(datetime.now().strftime("%H:%M:%S "), end='')
                                print("Error reply (not parsed)")

                            elif full_line_length == 24 and protocol_char == '\x18':
                                print(datetime.now().strftime("%H:%M:%S "), end='')
                                print("Status reply (not parsed)")

                            else:
                                # other type of message, or corrupted data
                                print(datetime.now().strftime("%H:%M:%S "), end='')
                                print(f"Message type not decoded:")
                                show_line_data = True

                            if show_line_data:
                                print(f"Received {full_line_length} (-{len(full_line)-len(data)} eol) bytes:{output_string}")
                                print(''.join(r" "+"{:02X}".format(letter) for letter in full_line))

                        time.sleep(0.1)  # Sleep for a short time to avoid excessive CPU usage

                else:
                    print(datetime.now().strftime("%H:%M:%S "), end='')
                    print(f"Failed to open port {port_name} at speed {baud_rate}")
                    time.sleep(2)   # sleep and then try the port again
            except KeyboardInterrupt:
                print(datetime.now().strftime("%H:%M:%S "), end='')
                print("Program interrupted.")
                if ser is not None:
                    print("Closing serial port.")
                    ser.close()
                exit()
            except Exception as e:
                print(datetime.now().strftime("%H:%M:%S "), end='')
                print(f"An error occurred: {e}")
                if ser is not None:
                    print("Closing serial port")
                    ser.close()
                time.sleep(2)   # sleep and then try to restart serial connection

        else:
            print(datetime.now().strftime("%H:%M:%S "), end='')
            print("No accepted serial ports found.")
            time.sleep(2)   # sleep and then try ports again
    else:
        print(datetime.now().strftime("%H:%M:%S "), end='')
        print("No serial ports found.")
        time.sleep(2)   # sleep and then try ports again
