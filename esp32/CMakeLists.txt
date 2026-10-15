# GAP-AI ESP32 firmware (ESP-IDF project).
# Target-independent: select the chip with `idf.py set-target <esp32|esp32s3|esp32c3|...>`.
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(gap_device)
