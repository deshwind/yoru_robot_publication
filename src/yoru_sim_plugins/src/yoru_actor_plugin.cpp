// ROS-driven human actor for Gazebo classic (Yoru simulation evaluation).
//
// Scripted actors (<script><trajectory>) cannot be moved at runtime and have
// no collision geometry, so the robot's lidar cannot see them. This plugin
// replaces the script with a custom trajectory driven from ROS:
//
//   <ns>/cmd_pose  geometry_msgs/PoseStamped (world frame)
//     header.frame_id == "teleport" -> jump there immediately
//     anything else                 -> walk there at walk_speed, then stand
//                                      facing the commanded yaw
//
// While moving it plays the "walking" animation (advanced by distance, as in
// Gazebo's ActorPlugin example); while still it plays "standing". Every
// update it also moves a separate static model (<body_model>, a collision
// cylinder) to the actor's ground position, so the person is an obstacle
// for the lidar, the costmaps and the e-stop.
//
// SDF parameters (all optional):
//   <body_model>      name of the collision model   (default: <actor>_body)
//   <walk_speed>      m/s                           (default: 0.6)
//   <turn_speed>      rad/s when turning in place   (default: 2.0)
//   <animation_factor> walk animation time per metre (default: 5.1)
//   <hip_height>      actor root height             (default: 1.0)
//   <ros><namespace>  topic namespace               (default: /<actor>)

#include <cmath>
#include <memory>
#include <mutex>
#include <string>

#include <gazebo/common/Plugin.hh>
#include <gazebo/common/Events.hh>
#include <gazebo/physics/physics.hh>
#include <gazebo_ros/node.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <ignition/math/Pose3.hh>
#include <rclcpp/rclcpp.hpp>

namespace yoru_sim_plugins
{

class YoruActorPlugin : public gazebo::ModelPlugin
{
public:
  void Load(gazebo::physics::ModelPtr model, sdf::ElementPtr sdf) override
  {
    actor_ = boost::dynamic_pointer_cast<gazebo::physics::Actor>(model);
    if (!actor_) {
      gzerr << "[yoru_actor_plugin] must be attached to an <actor>\n";
      return;
    }
    world_ = actor_->GetWorld();

    body_name_ = sdf->Get<std::string>("body_model", actor_->GetName() + "_body").first;
    walk_speed_ = sdf->Get<double>("walk_speed", 0.6).first;
    turn_speed_ = sdf->Get<double>("turn_speed", 2.0).first;
    animation_factor_ = sdf->Get<double>("animation_factor", 5.1).first;
    hip_height_ = sdf->Get<double>("hip_height", 1.0).first;

    // Start where the SDF <pose> put the actor, facing its SDF yaw
    const auto start = actor_->WorldPose();
    x_ = target_x_ = start.Pos().X();
    y_ = target_y_ = start.Pos().Y();
    yaw_ = target_yaw_ = start.Rot().Yaw();

    trajectory_ = std::make_shared<gazebo::physics::TrajectoryInfo>();
    trajectory_->type = "standing";
    trajectory_->duration = 1.0;
    actor_->SetCustomTrajectory(trajectory_);

    // <ros><namespace> if given, otherwise /<actor name>/cmd_pose
    ros_node_ = gazebo_ros::Node::Get(sdf);
    const std::string topic = sdf->HasElement("ros") ?
      "cmd_pose" : "/" + actor_->GetName() + "/cmd_pose";
    sub_ = ros_node_->create_subscription<geometry_msgs::msg::PoseStamped>(
      topic, 10,
      [this](const geometry_msgs::msg::PoseStamped::SharedPtr msg) {OnCommand(msg);});

    update_ = gazebo::event::Events::ConnectWorldUpdateBegin(
      std::bind(&YoruActorPlugin::OnUpdate, this, std::placeholders::_1));
    RCLCPP_INFO(
      ros_node_->get_logger(), "actor '%s' ready (body '%s', %.2f m/s)",
      actor_->GetName().c_str(), body_name_.c_str(), walk_speed_);
  }

private:
  void OnCommand(const geometry_msgs::msg::PoseStamped::SharedPtr msg)
  {
    const auto & q = msg->pose.orientation;
    const double yaw = std::atan2(2.0 * (q.w * q.z + q.x * q.y),
                                  1.0 - 2.0 * (q.y * q.y + q.z * q.z));
    std::lock_guard<std::mutex> lock(mutex_);
    target_x_ = msg->pose.position.x;
    target_y_ = msg->pose.position.y;
    target_yaw_ = yaw;
    if (msg->header.frame_id == "teleport") {
      // Kept until the next update even if a walk command follows at once
      // (teleport to a start point, then walk from there)
      teleport_ = true;
      teleport_x_ = target_x_;
      teleport_y_ = target_y_;
      teleport_yaw_ = yaw;
    }
  }

  static double Wrap(double a)
  {
    return std::atan2(std::sin(a), std::cos(a));
  }

  void OnUpdate(const gazebo::common::UpdateInfo & info)
  {
    double dt = (info.simTime - last_update_).Double();
    last_update_ = info.simTime;
    if (dt <= 0.0 || dt > 1.0) {
      dt = 0.0;  // first update or a world reset
    }

    double tx, ty, tyaw;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      tx = target_x_;
      ty = target_y_;
      tyaw = target_yaw_;
      if (teleport_) {
        x_ = teleport_x_;
        y_ = teleport_y_;
        yaw_ = teleport_yaw_;
        teleport_ = false;
      }
    }

    double moved = 0.0;
    const double dx = tx - x_, dy = ty - y_;
    const double dist = std::hypot(dx, dy);
    bool walking = false;
    if (dist > 0.02) {
      walking = true;
      const double heading = std::atan2(dy, dx);
      const double turn = Wrap(heading - yaw_);
      if (std::fabs(turn) > 0.35) {
        // Turn towards the goal first instead of walking sideways
        yaw_ = Wrap(yaw_ + std::copysign(std::min(std::fabs(turn), turn_speed_ * dt), turn));
      } else {
        yaw_ = heading;
        const double step = std::min(dist, walk_speed_ * dt);
        x_ += step * dx / dist;
        y_ += step * dy / dist;
        moved = step;
      }
    } else {
      const double turn = Wrap(tyaw - yaw_);
      yaw_ = Wrap(yaw_ + std::copysign(std::min(std::fabs(turn), turn_speed_ * dt), turn));
    }

    const std::string animation = walking ? "walking" : "standing";
    if (trajectory_->type != animation) {
      trajectory_->type = animation;
      actor_->SetCustomTrajectory(trajectory_);
    }

    // Actor skins are Y-up: roll by pi/2, and the mesh faces +Y, hence the
    // extra pi/2 on yaw (same convention as Gazebo's ActorPlugin example)
    ignition::math::Pose3d pose(x_, y_, hip_height_, M_PI_2, 0.0, yaw_ + M_PI_2);
    actor_->SetWorldPose(pose, false, false);
    actor_->SetScriptTime(actor_->ScriptTime() + (walking ? moved * animation_factor_ : dt));

    if (!body_) {
      body_ = world_->ModelByName(body_name_);
    }
    if (body_) {
      body_->SetWorldPose(ignition::math::Pose3d(x_, y_, 0.0, 0.0, 0.0, yaw_));
    }
  }

  gazebo::physics::ActorPtr actor_;
  gazebo::physics::WorldPtr world_;
  gazebo::physics::ModelPtr body_;
  gazebo::physics::TrajectoryInfoPtr trajectory_;
  gazebo::event::ConnectionPtr update_;
  gazebo_ros::Node::SharedPtr ros_node_;
  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr sub_;
  gazebo::common::Time last_update_;
  std::mutex mutex_;

  std::string body_name_;
  double walk_speed_{0.6}, turn_speed_{2.0}, animation_factor_{5.1}, hip_height_{1.0};
  double x_{0.0}, y_{0.0}, yaw_{0.0};
  double target_x_{0.0}, target_y_{0.0}, target_yaw_{0.0};
  bool teleport_{false};
  double teleport_x_{0.0}, teleport_y_{0.0}, teleport_yaw_{0.0};
};

GZ_REGISTER_MODEL_PLUGIN(YoruActorPlugin)

}  // namespace yoru_sim_plugins
