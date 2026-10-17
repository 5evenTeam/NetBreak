cmake_minimum_required(VERSION 3.16)
project(netbreak-native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
  add_compile_options(/W3 /O2)
else()
  add_compile_options(-Wall -Wextra -O3)
endif()

add_executable(netbreak-native src/main.cpp src/icmp.cpp)

if(MINGW)
  target_link_options(netbreak-native PRIVATE -static -static-libgcc -static-libstdc++)
endif()

if(WIN32)
  target_link_libraries(netbreak-native PRIVATE ws2_32 iphlpapi)
else()
  target_link_libraries(netbreak-native PRIVATE pthread)
endif()
