cmake_minimum_required(VERSION 3.8)
project(yoru_sim_plugins)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(gazebo_dev REQUIRED)
find_package(gazebo_ros REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)

add_library(yoru_actor_plugin SHARED src/yoru_actor_plugin.cpp)
ament_target_dependencies(yoru_actor_plugin
  gazebo_dev gazebo_ros rclcpp geometry_msgs)

install(TARGETS yoru_actor_plugin
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib)

ament_package()
